$ErrorActionPreference = "Stop"
$KeyInput = Read-Host "Enter your OpenAI API key (input is hidden)" -AsSecureString
$ApiKeyValue = [System.Net.NetworkCredential]::new("", $KeyInput).Password.Trim()
if ([string]::IsNullOrWhiteSpace($ApiKeyValue)) { throw "No key entered. Existing key was not changed." }
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", $ApiKeyValue, "User")
$env:OPENAI_API_KEY = $ApiKeyValue
$ApiKeyValue = $null
$KeyInput.Dispose()
Write-Host "OPENAI_API_KEY saved for this Windows user. The key is not printed."
Write-Host "Set ai.enabled to true in config.json, then restart Start-Watch.cmd."
Write-Host "This command does not make an API request or verify billing."
