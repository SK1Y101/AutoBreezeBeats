import nox

directories = ["src"]
lint_directories = ["noxfile.py"] + directories
format_directories = ["tests"] + lint_directories


@nox.session
def run(session: nox.session) -> None:
    session.install("-r", "requirements.txt")
    session.run("uvicorn", "src.main:app", "--reload", external=True)


@nox.session(tags=["format", "lint"])
def black(session: nox.session) -> None:
    session.install("black")
    session.run("black", *format_directories)


@nox.session(tags=["format", "lint"])
def isort(session: nox.session) -> None:
    session.install("isort")
    session.run("isort", "--profile", "black", *format_directories)


@nox.session(tags=["lint"])
def lint(session: nox.session) -> None:
    """Lint all python files."""
    session.install("flake8")
    session.run(
        "flake8",
        *lint_directories,
        "--max-line-length",
        "88",
        "--extend-ignore",
        "E203"
    )


@nox.session(tags=["lint"])
def mypy(session: nox.session) -> None:
    """Check python files for type violations."""
    mypy_directories = []
    for directory in directories:
        mypy_directories.extend(["-p", directory])

    session.install("mypy")
    session.install("-r", "requirements.txt")
    session.run("mypy", *mypy_directories, "--ignore-missing-imports")


@nox.session(tags=["test"])
def tests(session: nox.session) -> None:
    """Run the python test suite."""
    session.install("pytest")
    session.install("coverage")
    session.install("-r", "requirements.txt")
    session.run(
        "coverage",
        "run",
        "-m",
        "pytest",
        "tests",
        "--import-mode=importlib",
        "--durations=10",
        "-v",
    )
    session.run("coverage", "report", "-m")
