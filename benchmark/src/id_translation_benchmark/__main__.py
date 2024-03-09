from concurrent.futures import ProcessPoolExecutor

import click
from rics.performance import MultiCaseTimer


@click.command()
def cli():
    timer = MultiCaseTimer()
    print("hi!")


def run_in_new_process():
    ProcessPoolExecutor
    pass


if __name__ == "__main__":
    cli()
