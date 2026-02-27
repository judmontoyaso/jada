# Soul - Memoria de Jada

## .agent
- Cuando te pida mostrar un popup en PC, usa este comando:
```
Add-Type -AssemblyName Microsoft.VisualBasic
$mensaje = "MENSAJE_A_MOSTRAR"
$titulo = "Recordatorio"
$tiempoSegundos = 0
$wshell = New-Object -ComObject WScript.Shell
$wshell.Popup($mensaje, $tiempoSegundos, $titulo, 64)
```
Reemplaza "MENSAJE_A_MOSTRAR" con el mensaje que te indique.

- Para controlar el TV Samsung con SmartThings:
  1. Lee el token desde .env (SMARTTHINGS_TOKEN)
  2. Usa el script tv-control.ps1
  3. Sintaxis: `.\tv-control.ps1 -Action on|off -DeviceName "TV"`
  4. El script busca el dispositivo por nombre y envía el comando
  5. Muestra popup con el resultado