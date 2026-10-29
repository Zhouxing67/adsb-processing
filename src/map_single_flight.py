from adsb import Flight
from airport_surface import load_graph
from airport_workbench import flight_key, visualize
from path_map import map_flight


def main():
    flight = Flight.from_file(r"data\ADS-B\one_flight.csv")
    graph = load_graph(r"data\graphs\zbaa_final.json")
    path = map_flight(graph, flight)

    visualize(
        graph,
        flights=[flight],
        paths_by_flight_key={flight_key(0, "provided", flight.flight_id): path},
    )


if __name__ == "__main__":
    main()
