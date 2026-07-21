"""Example: Weather data tool server for Convilyn workflows.

Demonstrates the ToolServer + DataStore pattern.
"""

from convilyn_author import ToolServer

server = ToolServer(
    name="weather-data",
    description="Real-time weather data for location-based workflows",
    version="1.0.0",
    capabilities=["weather", "geocoding"],
)


@server.tool(
    description="Get current weather for a location",
    idempotent=True,
)
async def get_weather(location: str, units: str = "metric") -> dict:
    """Fetch current weather conditions.

    In production, this would call a real weather API.
    """
    result = {
        "location": location,
        "temperature": 22.5,
        "condition": "partly cloudy",
        "humidity": 65,
        "units": units,
    }
    ref_id = await server.data_store.store(result)
    return {"ref_id": ref_id, "summary": f"{location}: 22.5C, partly cloudy"}


@server.tool(description="Get weather forecast for upcoming days")
async def get_forecast(location: str, days: int = 7) -> dict:
    """Fetch multi-day weather forecast.

    In production, this would call a real weather API.
    """
    forecast = [
        {"day": i + 1, "high": 24 + i, "low": 16 + i, "condition": "sunny"} for i in range(days)
    ]
    result = {"location": location, "days": days, "forecast": forecast}
    ref_id = await server.data_store.store(result)
    return {"ref_id": ref_id, "summary": f"{location}: {days}-day forecast"}


if __name__ == "__main__":
    server.run()
