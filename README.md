# AutoBreezeBeats

Reinventing the radio, one bad line of code at a time.

**[Releases](../../releases)** **[Report a bug or suggestion](https://github.com/SK1Y101/AutoBreezeBeats/issues/new/choose)**

**[Road to 1.0](https://github.com/users/SK1Y101/projects/2)**
**[Road beyond 1.0](https://github.com/users/SK1Y101/projects/3)**

AutoBreezeBeats is a locally hosted, web accesible music player, leveraging the youtube API to stream video as audio to connected bluetooth devices.
Pair ABB with a curated `stored_songs.yaml` and an [OpenWeatherMap api key](https://openweathermap.org/api) to queue thematically appropriate songs for the current weather and time!

Note: Audio is **not** stored locally, ensure you have a decent connection!

Use at own risk.

## Using the program

Clone the project to a local area

```bash
$ git clone https://github.com/SK1Y101/AutoBreezeBeats.git
```

install nox and pactl

```bash
$ sudo apt install python3-nox
$ sudo apt install pavucontrol
```

Create a configuration file

```bash
$ nox -s config
```

and run the script

```bash
$ nox -s run
```

Simply navigate to [localhost:8000](http://localhost:8000/), and you'll be met with the web interface,
(Replace localhost with the IP of the host device if connecting from a seperate machine to the one running AutoBreezeBeats)

## Developing

### Out of control

If the script is running out of control, and ctrl+c is not working to halt it, you can find the process ids with 

```bash
ps aux | grep bluetooth-web-player
```

and run 

```bash
kill -9 $id
```

to halt it

### Code standards

A linter and formatter already exists for this project:

Running the tagged nox session will format and lint everything

```bash
$ nox -t lint
```

Under the hood, nox is execting the following sessions:

```
black isort lint mypy
```

Which can be executed individually with `$ nox -s $session`

To remove everything temporary created by running a nox session, run `$ nox -s clean`

### Helping out:

Pick up an issue, hack at the repo, even just fix a spelling mistake; be it backend, UI, or what-have-you, all contributions are welcome. Open a PR with your changes.

You can also [Report a bug or suggestion](https://github.com/SK1Y101/AutoBreezeBeats/issues/new/choose) using the standard github ettiquette.

An inexhaustitive roadmap for the project exists under [the project tab](https://github.com/users/SK1Y101/projects/2/views/2).
