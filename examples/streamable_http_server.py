#!/usr/bin/env python3
"""
Example MCP server using FastMCP with Streamable HTTP transport.

This server demonstrates how to create an MCP server that can be used
with the smart-agent's new streamable HTTP transport option.

Usage:
    python streamable_http_server.py

The server will start on http://localhost:8000/mcp
"""

import random
import requests
from mcp.server.fastmcp import FastMCP

# Create server
mcp = FastMCP("Example Streamable HTTP Server")


@mcp.tool()
def add_numbers(a: int, b: int) -> int:
    """Add two numbers together"""
    print(f"[server] add_numbers({a}, {b}) = {a + b}")
    return a + b


@mcp.tool()
def get_random_fact() -> str:
    """Get a random interesting fact"""
    facts = [
        "Honey never spoils. Archaeologists have found pots of honey in ancient Egyptian tombs that are over 3,000 years old and still perfectly edible.",
        "A group of flamingos is called a 'flamboyance'.",
        "Octopuses have three hearts and blue blood.",
        "The shortest war in history lasted only 38-45 minutes between Britain and Zanzibar in 1896.",
        "Bananas are berries, but strawberries aren't.",
        "A single cloud can weigh more than a million pounds.",
        "There are more possible games of chess than there are atoms in the observable universe."
    ]
    fact = random.choice(facts)
    print(f"[server] get_random_fact() = {fact[:50]}...")
    return fact


@mcp.tool()
def get_weather_info(city: str) -> str:
    """Get weather information for a city using a simple weather API"""
    print(f"[server] get_weather_info({city})")
    
    try:
        # Using wttr.in for simple weather data
        endpoint = "https://wttr.in"
        response = requests.get(f"{endpoint}/{city}?format=3", timeout=10)
        if response.status_code == 200:
            weather_info = response.text.strip()
            print(f"[server] Weather for {city}: {weather_info}")
            return f"Weather in {city}: {weather_info}"
        else:
            return f"Could not get weather information for {city}"
    except Exception as e:
        print(f"[server] Error getting weather: {e}")
        return f"Error getting weather for {city}: {str(e)}"


@mcp.tool()
def calculate_fibonacci(n: int) -> int:
    """Calculate the nth Fibonacci number"""
    print(f"[server] calculate_fibonacci({n})")
    
    if n < 0:
        return 0
    elif n <= 1:
        return n
    
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    
    print(f"[server] Fibonacci({n}) = {b}")
    return b


if __name__ == "__main__":
    print("Starting Streamable HTTP MCP Server...")
    print("Server will be available at: http://localhost:8000/mcp")
    print("Use Ctrl+C to stop the server")
    
    # Run with streamable-http transport
    mcp.run(transport="streamable-http", host="localhost", port=8000)