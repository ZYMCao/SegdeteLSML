"""Run segdete with the pseudocamera shim installed."""

import sys


def main(argv=None):
    from pseudocamera import shim

    shim.install()
    from segdete import cli

    sys.argv = ["cli", *(sys.argv[1:] if argv is None else argv)]
    cli.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
