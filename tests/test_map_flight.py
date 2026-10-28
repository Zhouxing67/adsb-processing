from traffic.core import Flight

from airport_surface import load_graph
from airport_workbench import open_workbench
from path_map import MovementType, map_flight


def main():
    flight = Flight.from_file(r"data\ADS-B\one_flight.csv")
    graph = load_graph(r"data\graphs\zbaa_final_V1.json")
    path = map_flight(graph, flight, movement_type=MovementType.ARRIVAL)

    open_workbench(
        graph,
        flights=[flight],
        paths=[path],
    )


if __name__ == "__main__":
    main()
