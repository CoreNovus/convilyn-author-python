<p align="center">
  <img src="docs/assets/corenovus-community-banner.png" alt="CoreNovus Community — Connected AI Workflows" />
</p>

# convilyn-author

[![CI](https://github.com/CoreNovus/convilyn-author-python/actions/workflows/ci.yml/badge.svg)](https://github.com/CoreNovus/convilyn-author-python/actions/workflows/ci.yml)

Official Convilyn author SDK — build and host the tool servers that power the Convilyn AI platform's workflows.

Convilyn Author helps builders turn tools, services, and repeated processes into reusable workflow building blocks. It is part of the CoreNovus vision for practical AI workflows across cloud services, local machines, AI PCs, edge devices, and future IoT environments.

> **Public mirror** of Convilyn's monorepo (the source of truth). Contributions are
> welcome and land in the shipped package — see
> **[CONTRIBUTING.md](CONTRIBUTING.md)** (fork → PR → upstreamed, authorship preserved).

## What is Convilyn Author?

Convilyn Author is an open source Python SDK for creating tool servers for Convilyn. (Workflows themselves are authored in the Convilyn chat Builder; this SDK builds the MCP tool servers those workflows call.)

It helps developers expose useful capabilities as reusable tools, run them locally during development, and host them on their own infrastructure. This makes it easier for the community to build, share, and maintain tool servers that others can use.

## Who is this for?

Convilyn Author is for:

- Developers building tool servers for AI workflows
- Builders creating reusable workflow components
- Teams standardizing repeated processes
- People experimenting with local-first and edge-ready AI workflows
- Contributors who want to help expand the Convilyn community library

## Install

```bash
uv add convilyn-author   # or: pip install convilyn-author
```

## Quickstart

```bash
uv add convilyn-author   # or: pip install convilyn-author
convilyn-author init my-server     # scaffold a tool server
cd my-server                       # edit server.py — add @server.tool functions
convilyn-author dev                # run locally (no secret needed)
```

Free to install; you host your tool server on your own infra (Lambda / Fargate /
VM) and Convilyn bills the *caller* of your tools, not you.

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for the HMAC contract + billing model,
**[docs/STABILITY.md](docs/STABILITY.md)** for the SemVer promise, and the full docs at:

[https://docs.convilyn.com](https://docs.convilyn.com)

## Community

Convilyn Author is maintained by CoreNovus, an independent developer team building open source tools for reusable AI workflows.

We welcome contributions from people who want to help improve documentation, examples, tests, local development experience, tool server patterns, and deployment guidance.

A useful workflow component should not stay locked inside one project. It should become something others can learn from, adapt, host, and reuse in their own context.

Start here:

* [Contributing Guide](CONTRIBUTING.md)
* [Code of Conduct](CODE_OF_CONDUCT.md)
* [Good first issues](https://github.com/CoreNovus/convilyn-author-python/labels/good%20first%20issue)
* [CoreNovus on GitHub](https://github.com/CoreNovus)

## Project direction

CoreNovus is building toward a world where AI workflows can move beyond one-time chat sessions.

Convilyn Author focuses on the tool-server side: the reusable capabilities that platform workflows call. Together with the Convilyn client SDK, it helps make workflows easier to create, save, run, share, and eventually bring across cloud, local, and real-world environments.

## Contributing

We use the **DCO** (`git commit -s`) — no CLA.

Start with [CONTRIBUTING.md](CONTRIBUTING.md), the [Code of Conduct](CODE_OF_CONDUCT.md), and [good first issues](https://github.com/CoreNovus/convilyn-author-python/labels/good%20first%20issue).

Small documentation fixes, examples, tests, and issue reports are especially welcome.

## Security

Please report vulnerabilities privately — see [SECURITY.md](SECURITY.md).

Do not open a public GitHub issue for security vulnerabilities.

## License

[Apache-2.0](LICENSE).
