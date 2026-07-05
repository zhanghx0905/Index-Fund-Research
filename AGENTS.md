# Repository Instructions

注意：本机默认 shell 是 PowerShell。执行命令时请使用 PowerShell 语法，不要使用 bash/cmd 写法。

处理中文或写入文件时请显式使用 UTF-8 编码，例如 PowerShell 5.1 中使用 `-Encoding UTF8`，避免依赖默认编码。不要假设当前代码页是 UTF-8；如涉及控制台编码，请先检查或设置：

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

## Structure

- `nq-leverage/`: preserves the corrected B-ADJ TQQQ vs MNQ/NQ methodology. Read its local `AGENTS.md` before changing those scripts or conclusions.
- `qqq-volatility/`: preserves QQQ volatility regime logic. Read its local `AGENTS.md` before changing thresholds or chart outputs.
- `optimal-leverage-rates/`: studies daily-rebalanced NDX/SPX leverage using historical short-rate financing.

## Research Standards

- Keep raw inputs, generated outputs, and scripts separate.
- Do not commit raw market-data caches or generated CSV/JSON tables unless the user explicitly asks for them.
- Do not hand-edit generated CSV, HTML, or PNG outputs; regenerate them from scripts.
- State data source, sample window, return definition, leverage rule, and major omissions whenever updating conclusions.
- Treat all results as historical research, not investment advice.
