import questionary
import yaml
import os

def get_location():
    choice = questionary.select(
        "Do you want to enter latitude/longitude or city name?",
        choices=[
            "Latitude/Longitude",
            "City Name"
        ]
    ).ask()

    match choice:
        case "Latitude/Longitude":
            lat = questionary.text("Enter latitude:").ask()
            lon = questionary.text("Enter longitude:").ask()
            try:
                lat = float(lat)
                lon = float(lon)
                return {"latitude": lat, "longitude": lon}
            except ValueError:
                print("Invalid latitude or longitude. Please enter numerical values.")

        case "City Name":
            city = questionary.text("Enter city name:").ask()
            country = questionary.text("Enter country code:").ask()
            if city and country:
                return {"city": city, "country": country}
            else:
                print("City name and country code cannot be empty. Please try again.")
    
    return get_location()

def get_api_key():
    api_key = questionary.password("Enter your OpenWeather API key:").ask()
    if api_key:
        return api_key
    print("API key cannot be empty. Please try again.")
    return get_api_key()

def save_config(config, filename="config.yaml"):
    with open(filename, "w") as f:
        yaml.safe_dump(config, f)

if __name__ == "__main__":
    config = {}
    config["weather"] = {}
    config["weather"]["location"] = get_location()
    config["weather"]["api_key"] = get_api_key()

    save_config(config)
    print(f"Configuration saved to {os.path.abspath("config.yaml")}")
