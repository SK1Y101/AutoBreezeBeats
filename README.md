# AutoBreezeBeats

Reinventing the radio, one bad line of code at a time.

**[Releases](../../releases)**

AutoBreezeBeats is a locally hosted, web accesible music player, leveraging the youtube API to stream video as audio to connected bluetooth devices.

## Using the program

Clone the project to a local area

```bash
$ git clone https://github.com/SK1Y101/AutoBreezeBeats.git
```

install nox

```bash
$ sudo apt install python3-nox
```

and run the script

```bash
$ nox -s run
```

Simply navigate to $ip:8000, and you'll be met with the web interface,

## Developing

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

An inexhaustitive roadmap for the project exists under [the project tab](https://github.com/users/SK1Y101/projects/2/views/2).