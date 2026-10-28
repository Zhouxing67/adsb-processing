from adsb import Flights
from airport_surface import load_graph
from path_map import map_flight


def main():
    flights = Flights.from_file(r"data\ADS-B\more_15_arr.csv")
    graph = load_graph(r"data\graphs\zbaa_final.json")


    for idx, flight in enumerate(flights):
        print(f"开始匹配第{idx+1}个轨迹")
        map_flight(graph, flight)


if __name__ == "__main__":
    main()
