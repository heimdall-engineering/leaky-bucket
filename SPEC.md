# Burst Congestion Simulation (Project "LeakyBucket")

## 1. Objective

Build a 2D microscopic traffic simulation to evaluate strategies for clearing high-density passenger bursts (e.g., stadium events) using ride-sharing. The goal is to compare standard "unregulated" dispatching against OR-inspired strategies like Leaky Bucket Rate Limiting and Virtual Queuing.

## 2. Technical Stack

- **Engine:** Eclipse SUMO (Simulation of Urban MObility)
- **Language:** Python 3.10+
- **Control Interface:** traci (Traffic Control Interface)
- **Map Data:** OpenStreetMap (OSM) export of a stadium area (e.g., Levi's Stadium, Santa Clara)
- **Visualization:** sumo-gui for real-time 2D view; matplotlib or streamlit for live KPI dashboard

## 3. Simulation Parameters

### A. The "Burst" Demand (The Herd)

- **Event Location:** A designated "Pickup Plaza" geofence
- **Demand Volume:** 2,000 "Person" agents appearing simultaneously at T=0
- **Destination Distribution:** Randomized points across the map periphery
- **Mode:** All persons attempt to request an "Uber" agent

### B. The Supply (The Fleet)

- **Fleet Size:** 200 dedicated "Driver" agents
- **Starting State:** Distributed randomly or idling in a nearby "Staging Lot"
- **States:** IDLE, EN_ROUTE_TO_PICKUP, OCCUPIED, RETURNING_TO_STAGING

## 4. Operational Strategies (The "Logic" Modules)

The agent must implement a modular Dispatcher class to toggle between:

### Baseline (Naive)
- Immediate matching
- As soon as a request exists, the nearest available driver is dispatched

### Leaky Bucket (Rate Limiting)
- **Bucket Size (B):** Max number of active "Match" tokens
- **Leak Rate (R):** Tokens released per minute
- **Logic:** Requests enter a queue and are only matched when a token "leaks," preventing a swarm of cars from entering the stadium geofence simultaneously

### Virtual Queuing (Incentivized Smoothing)
- **Logic:** Users are assigned "Window Slots." If a user accepts a later slot, their simulated "priority" or "cost" is adjusted

## 5. KPI Requirements

The simulation must output a real-time CSV or JSON stream of the following metrics:

| Metric Category | Key Performance Indicator (KPI) | Formula / Logic |
|-----------------|----------------------------------|-----------------|
| Rider | Average Wait Time (AWT) | Time from Request to traci.person.setVehicle |
| Rider | 95th% Tail Latency | The wait time for the slowest 5% of riders |
| System | Clearance Rate | Number of passengers delivered per 100 simulation steps |
| System | Gridlock Factor | Average speed of vehicles within 500m of the stadium |
| Driver | Utilization Rate | (Time Occupied) / (Total Sim Time) |
| Quality | Braking Intensity Index | Count of traci.vehicle.getAcceleration < -4.5 m/s^2 |

## 6. Implementation Steps

### Phase 1: Environment Setup

- [ ] Generate a SUMO network file (.net.xml) from an OSM area
- [ ] Define vehicle types for "UberX" (high acceleration) and "Buses" (high capacity)
- [ ] Script the "Burst" arrival in the .rou.xml file

### Phase 2: The TraCI Controller

- [ ] Initialize the simulation via traci.start()
- [ ] Implement the Step() loop to monitor person states
- [ ] Build the MatchMaker logic to assign vehicleID to personID

### Phase 3: The OR Logic

- [ ] Create a TokenBucket class to throttle the MatchMaker
- [ ] Implement a "Staging Area" logic where cars wait until "called" by the bucket

### Phase 4: Data Export & Visualization

- [ ] Log KPIs to a local file every N steps
- [ ] (Optional) Create a Streamlit dashboard to visualize the .csv output as the simulation runs

## 7. Success Criteria

- **Visual Confirmation:** In sumo-gui, cars should not form a complete standstill (gridlock) around the pickup zone
- **Data Confirmation:** The "Leaky Bucket" strategy should show a lower 95th% Wait Time and higher Gridlock Speed compared to the Baseline, even if Average Wait Time is slightly higher