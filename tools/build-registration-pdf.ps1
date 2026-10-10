param(
  [string]$Source = (Join-Path $PSScriptRoot '..\docs\datto-siris-registration-flow.md'),
  [string]$Output = (Join-Path $PSScriptRoot '..\docs\datto-siris-registration-flow.pdf')
)

$ErrorActionPreference = 'Stop'

$sourcePath = [IO.Path]::GetFullPath($Source)
$outputPath = [IO.Path]::GetFullPath($Output)
if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
  throw "Markdown source not found: $sourcePath"
}

$browserCandidates = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
)
$browser = $browserCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_ -PathType Leaf) } | Select-Object -First 1
if (-not $browser) {
  throw 'Chrome or Edge is required to render the PDF.'
}

$markdown = Get-Content -Raw -LiteralPath $sourcePath
$body = (ConvertFrom-Markdown -InputObject $markdown).Html
$title = 'Datto SIRIS registration workflow'
$css = @'
@page { size: Letter; margin: 0.62in 0.68in 0.68in; }
* { box-sizing: border-box; }
body {
  color: #202124;
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: 10.5pt;
  line-height: 1.45;
  margin: 0;
}
h1, h2 { color: #17202a; font-family: Georgia, "Times New Roman", serif; }
h1 { font-size: 27pt; line-height: 1.08; margin: 0 0 12pt; }
h2 { font-size: 17pt; margin: 24pt 0 8pt; break-after: avoid; }
p { margin: 0 0 8pt; }
ul, ol { margin: 5pt 0 10pt 19pt; padding: 0; }
li { margin: 2pt 0; }
table { border-collapse: collapse; font-size: 8.6pt; margin: 10pt 0 14pt; width: 100%; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th, td { border: 1px solid #d8d5cc; padding: 5pt 6pt; text-align: left; vertical-align: top; }
th { background: #f3f1eb; color: #4d4d4d; font-weight: 600; }
code { background: #f3f1ed; border-radius: 3px; font-family: Consolas, monospace; font-size: 0.92em; padding: 1px 3px; }
pre { background: #f7f6f2; border: 1px solid #dedbd2; border-radius: 6px; break-inside: avoid; line-height: 1.3; padding: 10pt 12pt; }
pre code { background: none; padding: 0; }
em { color: #666; }
strong { color: #202124; }
'@

$html = @"
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>$title</title>
  <style>$css</style>
</head>
<body>$body</body>
</html>
"@

$outputDirectory = Split-Path -Parent $outputPath
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$tempHtml = Join-Path ([IO.Path]::GetTempPath()) ("backops-registration-{0}.html" -f [guid]::NewGuid())

try {
  [IO.File]::WriteAllText($tempHtml, $html, [Text.UTF8Encoding]::new($false))
  $uri = ([Uri]$tempHtml).AbsoluteUri
  $arguments = @(
    '--headless=new',
    '--disable-gpu',
    '--no-pdf-header-footer',
    "--print-to-pdf=$outputPath",
    $uri
  )
  & $browser @arguments | Out-Null
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
    throw "PDF rendering failed with exit code $LASTEXITCODE"
  }
  $size = (Get-Item -LiteralPath $outputPath).Length
  if ($size -lt 1024) { throw "Rendered PDF is unexpectedly small: $size bytes" }
  Write-Output "Rendered $outputPath ($size bytes)"
}
finally {
  if (Test-Path -LiteralPath $tempHtml) { Remove-Item -LiteralPath $tempHtml -Force }
}
