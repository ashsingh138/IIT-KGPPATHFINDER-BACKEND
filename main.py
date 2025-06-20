from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import osmnx as ox
import networkx as nx
from geopy.geocoders import Nominatim
import math

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("Loading graph data for IIT Kharagpur...")
place = "Indian Institute of Technology Kharagpur, West Bengal, India"
G = ox.graph_from_place(place, network_type='walk')
G = G.to_undirected()
print("Graph data loaded successfully.")

# ▼ HELPER FUNCTIONS FOR CALCULATING TURN DIRECTIONS ▼

def calculate_bearing(lat1, lon1, lat2, lon2):
    """Calculates the bearing (direction) between two GPS points."""
    dLon = math.radians(lon2 - lon1)
    y = math.sin(dLon) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - \
        math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dLon)
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    return bearing

def get_turn_instruction(angle):
    """Translates a turn angle into a human-readable instruction."""
    if -20 <= angle <= 20:
        return "Continue straight"
    elif angle > 20 and angle <= 65:
        return "Make a slight right"
    elif angle > 65 and angle <= 135:
        return "Turn right"
    elif angle < -20 and angle >= -65:
        return "Make a slight left"
    elif angle < -65 and angle >= -135:
        return "Turn left"
    elif angle > 135:
        return "Make a sharp right"
    else: # angle < -135
        return "Make a sharp left"

# ▲ END OF HELPER FUNCTIONS ▲

@app.get("/reverse-geocode")
def reverse_geocode(lat: float, lon: float):
    # This endpoint remains the same
    try:
        geolocator = Nominatim(user_agent="iit-kharagpur-pathfinder")
        location = geolocator.reverse((lat, lon), exactly_one=True, timeout=10)
        return {"name": location.address if location else "Unknown location"}
    except Exception as e:
        print(f"An error occurred during reverse geocoding: {e}")
        raise HTTPException(status_code=500, detail="Reverse geocoding service failed.")

@app.post("/shortest-path")
async def get_path(request: Request):
    data = await request.json()
    source_point_data = data['source']
    dest_point_data = data['target']
    src_coords = (source_point_data['lat'], source_point_data['lon'])
    dst_coords = (dest_point_data['lat'], dest_point_data['lon'])
    src_node = ox.distance.nearest_nodes(G, src_coords[1], src_coords[0])
    dst_node = ox.distance.nearest_nodes(G, dst_coords[1], dst_coords[0])
    
    path_nodes = nx.shortest_path(G, src_node, dst_node, weight='length')
    path_coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in path_nodes]
    total_distance = nx.shortest_path_length(G, src_node, dst_node, weight='length')

    # ▼ FINAL, ADVANCED LOGIC FOR DETAILED DIRECTIONS ▼
    directions = []
    if len(path_nodes) < 2:
        return { "path": path_coords, "distance": round(total_distance, 2), "directions": [] }
    
    # Manually get edge attributes for robustness
    route_edges = []
    for u, v in zip(path_nodes[:-1], path_nodes[1:]):
        edge_data = G.get_edge_data(u, v)[0].copy()
        route_edges.append(edge_data)

    # Initial instruction
    first_edge = route_edges[0]
    street_name = first_edge.get('name', 'Unnamed Path')
    if isinstance(street_name, list): street_name = street_name[0]
    directions.append({"instruction": f"Head toward <strong>{street_name}</strong>", "distance": round(first_edge.get('length', 0))})

    # Iterate through the path to find turns
    for i in range(1, len(path_nodes) - 1):
        # Get the nodes for the intersection: previous, current (junction), and next
        prev_node = G.nodes[path_nodes[i-1]]
        curr_node = G.nodes[path_nodes[i]]
        next_node = G.nodes[path_nodes[i+1]]

        # Calculate bearings
        bearing1 = calculate_bearing(prev_node['y'], prev_node['x'], curr_node['y'], curr_node['x'])
        bearing2 = calculate_bearing(curr_node['y'], curr_node['x'], next_node['y'], next_node['x'])

        # Calculate turn angle
        turn_angle = bearing2 - bearing1
        if turn_angle > 180: turn_angle -= 360
        if turn_angle < -180: turn_angle += 360
        
        turn_instruction = get_turn_instruction(turn_angle)

        # Get the name of the street you are turning onto
        next_edge = route_edges[i]
        next_street_name = next_edge.get('name', 'Unnamed Path')
        if isinstance(next_street_name, list): next_street_name = next_street_name[0]
        
        # Add an instruction only if there is a meaningful turn
        if turn_instruction != "Continue straight":
            directions.append({
                "instruction": f"{turn_instruction} onto <strong>{next_street_name}</strong>",
                "distance": round(next_edge.get('length', 0))
            })

    return {
        "path": path_coords, 
        "distance": round(total_distance, 2),
        "directions": directions
    }