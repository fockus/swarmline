# ISS - Moscow Exchange Data

Use ISS tools for searching bonds and stocks on the Moscow Exchange (MOEX).

## Available Tools

- `mcp__iss__search_bonds` - Search bonds by parameters (coupon, maturity, rating)
- `mcp__iss__get_emitter` - Get emitter information by ID

## Guidelines

- Always specify currency when searching bonds (default: RUB)
- Use ISIN codes for precise identification
- Results are cached for 5 minutes
