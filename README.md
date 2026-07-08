# convilyn-author

[![CI](https://github.com/CoreNovus/convilyn-author-python/actions/workflows/ci.yml/badge.svg)](https://github.com/CoreNovus/convilyn-author-python/actions/workflows/ci.yml)

Official Convilyn author SDK — build & host tool servers and author workflow specs for the Convilyn AI platform.

> **Public mirror** of Convilyn's monorepo (the source of truth). Contributions are
> welcome and land in the shipped package — see
> **[CONTRIBUTING.md](CONTRIBUTING.md)** (fork → PR → upstreamed, authorship preserved).

## Install

```bash
pip install convilyn-author
```

## Quickstart

```bash
pip install convilyn-author
convilyn-author init my-server     # scaffold a tool server
cd my-server                       # edit server.py — add @server.tool functions
convilyn-author dev                # run locally (no secret needed)
```

Free to install; you host your tool server on your own infra (Lambda / Fargate /
VM) and Convilyn bills the *caller* of your tools, not you. See
**[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for the HMAC contract + billing model,
**[docs/STABILITY.md](docs/STABILITY.md)** for the SemVer promise, and the full docs
at <https://docs.convilyn.corenovus.com>.


## Contributing

We use the **DCO** (`git commit -s`) — no CLA. Start with
[CONTRIBUTING.md](CONTRIBUTING.md), the [Code of Conduct](CODE_OF_CONDUCT.md), and
[good first issues](https://github.com/CoreNovus/convilyn-author-python/labels/good%20first%20issue).

## Security

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

## License

[Apache-2.0](LICENSE).
