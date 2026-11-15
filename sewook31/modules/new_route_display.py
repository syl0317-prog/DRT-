"""Display the complete validated OSRM model, without synthetic connectors."""


def display_geometry(route_id, stops, road):
    full = [road['coordinates']] if road else []
    return dict(display_paths=full, visualization_paths=[])
