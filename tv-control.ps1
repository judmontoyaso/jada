# SmartThings TV Control
# Juan - MiniClaw

param(
    [string]$Action = "on",
    [string]$DeviceName = "TV"
)

# Cargar token desde .env
$envPath = Join-Path $PSScriptRoot ".env"
if (Test-Path $envPath) {
    Get-Content $envPath | Where-Object { $_ -match 'SMARTTHINGS_TOKEN=' } | ForEach-Object {
        $script:Token = ($_ -split '=')[1].Trim()
    }
}

if (-not $Token) {
    Write-Error "Token no encontrado en .env (SMARTTHINGS_TOKEN)"
    exit 1
}

$Headers = @{
    "Authorization" = "Bearer $Token"
    "Content-Type" = "application/json"
}

# Obtener dispositivos
$DevicesUrl = "https://api.smartthings.com/v1/devices"
$Devices = Invoke-RestMethod -Uri $DevicesUrl -Headers $Headers -Method Get

# Buscar TV por nombre
$TV = $Devices.items | Where-Object { $_.label -like "*$DeviceName*" -or $_.name -like "*$DeviceName*" }

if (-not $TV) {
    Write-Error "No se encontró dispositivo con nombre: $DeviceName"
    Write-Host "Dispositivos disponibles:"
    $Devices.items | ForEach-Object { Write-Host "  - $($_.label) [$($_.deviceId)]" }
    exit 1
}

# Comando según la acción
if ($Action -eq "on") {
    $Command = @{
        capability = "switch"
        command = "on"
    }
    $Mensaje = "TV encendido ✅"
} elseif ($Action -eq "off") {
    $Command = @{
        capability = "switch"
        command = "off"
    }
    $Mensaje = "TV apagado 🔇"
} else {
    Write-Error "Acción no válida: on/off"
    exit 1
}

# Enviar comando
$Body = @{
    commands = @($Command)
} | ConvertTo-Json -Depth 3

$Url = "https://api.smartthings.com/v1/devices/$($TV.deviceId)/commands"
$Response = Invoke-RestMethod -Uri $Url -Headers $Headers -Method Post -Body $Body

# Mostrar popup
Add-Type -AssemblyName Microsoft.VisualBasic
$wshell = New-Object -ComObject WScript.Shell
$wshell.Popup($Mensaje, 3, "Samsung TV Control", 64)

Write-Host $Mensaje