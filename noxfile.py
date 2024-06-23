import nox

code_directories = ["src"]
lint_directories = ["noxfile.py"] + code_directories
format_directories = ["tests"] + lint_directories


@nox.session(tags=["run"])
def run(session: nox.session) -> None:
    session.install("-r", "requirements.txt")
    session.run(
        "uvicorn", "src.main:app", "--reload", "--reload-dir", "src", external=True
    )


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
    """Lint all files."""
    session.install("flake8")
    session.run(
        "flake8",
        *lint_directories,
        "--max-line-length",
        "88",
        "--extend-ignore",
        "E203",
    )


@nox.session(tags=["lint"])
def mypy(session: nox.session) -> None:
    """Check python files for type violations."""
    mypy_directories = []
    for directory in code_directories:
        mypy_directories.extend(["-p", directory])

    session.install("mypy")
    session.install("-r", "requirements.txt")
    session.run("mypy", *mypy_directories, "--ignore-missing-imports")


@nox.session
def clean(session: nox.session) -> None:
    """Cleanup any created items."""
    import os
    import shutil

    def delete(directory):
        shutil.rmtree(directory, ignore_errors=True)

    def delete_file(file):
        os.remove(file)

    delete("src/__pycache__")
    delete("__pycache__")
    delete(".mypy_cache")
    delete(".pytest_cache")
    delete(".nox")

    delete_file(".coverage")


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
