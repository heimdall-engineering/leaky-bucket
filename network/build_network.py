"""Download OSM data and convert to a SUMO network.

Usage:
    python -m network.build_network [--lat 37.4033] [--lon -121.9694] [--radius 2000]

Requires: osmWebWizard.py or manual OSM download + netconvert (shipped with SUMO).
"""

import argparse
import logging
import math
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

NETWORK_DIR = Path(__file__).parent


def lat_lon_bbox(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Compute a bounding box (west, south, east, north) from a center point and radius."""
    lat_offset = radius_m / 111_320.0
    lon_offset = radius_m / (111_320.0 * math.cos(math.radians(lat)))
    return (
        lon - lon_offset,  # west
        lat - lat_offset,  # south
        lon + lon_offset,  # east
        lat + lat_offset,  # north
    )


def download_osm(bbox: tuple[float, float, float, float], output_path: Path) -> None:
    """Download OSM data via the Overpass API."""
    import urllib.request

    west, south, east, north = bbox
    url = (
        f"https://overpass-api.de/api/map?bbox={west},{south},{east},{north}"
    )
    logger.info("Downloading OSM data from Overpass API...")
    logger.info("  bbox: %s", bbox)
    urllib.request.urlretrieve(url, str(output_path))
    logger.info("  Saved to %s (%.1f KB)", output_path, output_path.stat().st_size / 1024)


def convert_to_sumo_net(osm_path: Path, net_path: Path) -> None:
    """Convert OSM XML to SUMO .net.xml using netconvert."""
    cmd = [
        "netconvert",
        "--osm-files", str(osm_path),
        "--output-file", str(net_path),
        "--geometry.remove",
        "--ramps.guess",
        "--junctions.join",
        "--tls.guess-signals",
        "--tls.discard-simple",
        "--tls.join",
        "--tls.default-type", "actuated",
        "--junctions.corner-detail", "5",
        "--output.street-names",
        "--output.original-names",
    ]
    logger.info("Running netconvert...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("netconvert failed:\n%s", result.stderr)
        sys.exit(1)
    logger.info("  Network written to %s", net_path)


def generate_sumocfg(net_file: str, route_file: str, additional: str, cfg_path: Path) -> None:
    """Write a .sumocfg XML file."""
    cfg_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
               xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">
    <input>
        <net-file value="{net_file}"/>
        <route-files value="{route_file}"/>
        <additional-files value="{additional}"/>
    </input>
    <time>
        <begin value="0"/>
        <end value="7200"/>
        <step-length value="1.0"/>
    </time>
    <processing>
        <lateral-resolution value="0.8"/>
    </processing>
    <report>
        <no-step-log value="true"/>
    </report>
</configuration>
"""
    cfg_path.write_text(cfg_content)
    logger.info("  SUMO config written to %s", cfg_path)


def generate_vehicle_types(output_path: Path) -> None:
    """Generate vehicle type definitions (UberX and Bus)."""
    content = """<?xml version="1.0" encoding="UTF-8"?>
<additional>
    <vType id="uberx" accel="3.0" decel="5.0" sigma="0.5"
           length="4.5" maxSpeed="50.0" speedFactor="1.0"
           color="1,0.65,0" guiShape="passenger"/>
    <vType id="bus" accel="1.2" decel="4.0" sigma="0.5"
           length="12.0" maxSpeed="30.0" speedFactor="0.9"
           personCapacity="50" color="0,0.5,1" guiShape="bus"/>
</additional>
"""
    output_path.write_text(content)
    logger.info("  Vehicle types written to %s", output_path)


def generate_empty_routes(output_path: Path) -> None:
    """Generate an empty route file (routes are created dynamically via traci)."""
    content = """<?xml version="1.0" encoding="UTF-8"?>
<routes>
</routes>
"""
    output_path.write_text(content)
    logger.info("  Route file written to %s", output_path)


def build(lat: float = 37.4033, lon: float = -121.9694, radius_m: float = 2000.0) -> None:
    """Full pipeline: download OSM -> netconvert -> write sumocfg + vehicle types."""
    osm_path = NETWORK_DIR / "stadium.osm"
    net_path = NETWORK_DIR / "stadium.net.xml"
    cfg_path = NETWORK_DIR / "stadium.sumocfg"
    vtypes_path = NETWORK_DIR / "vehicle_types.xml"
    route_path = NETWORK_DIR / "stadium.rou.xml"

    bbox = lat_lon_bbox(lat, lon, radius_m)

    if not osm_path.exists():
        download_osm(bbox, osm_path)
    else:
        logger.info("OSM file already exists, skipping download: %s", osm_path)

    convert_to_sumo_net(osm_path, net_path)
    generate_vehicle_types(vtypes_path)
    generate_empty_routes(route_path)
    generate_sumocfg(
        net_file="stadium.net.xml",
        route_file="stadium.rou.xml",
        additional="vehicle_types.xml",
        cfg_path=cfg_path,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Build SUMO network from OSM")
    parser.add_argument("--lat", type=float, default=37.4033)
    parser.add_argument("--lon", type=float, default=-121.9694)
    parser.add_argument("--radius", type=float, default=2000.0)
    args = parser.parse_args()
    build(args.lat, args.lon, args.radius)
