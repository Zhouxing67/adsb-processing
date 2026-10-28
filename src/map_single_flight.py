from adsb import Flight
from airport_surface import load_graph
from airport_workbench import visualize
from path_map import map_flight


def main():
    flight = Flight.from_file(r"data\ADS-B\one_flight.csv")
    graph = load_graph(r"data\graphs\zbaa_final.json")
    path = map_flight(graph, flight)

    visualize(
        graph,
        flights=[flight],
        paths=[path],
    )


if __name__ == "__main__":
    main()
