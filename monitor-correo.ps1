param(
    [string]$Username = "juandavidsolorzano73@gmail.com",
    [string]$Password = "gtlb tzpy jeuk leep",
    [string]$Domain = "albertoalvarez.com",
    [int]$CheckInterval = 60
)

$IMAPServer = "imap.gmail.com"
$IMAPPort = 993

Add-Type -AssemblyName Microsoft.VisualBasic

function Check-Emails {
    try {
        $tcp = New-Object Net.Sockets.TcpClient
        $tcp.Connect($IMAPServer, $IMAPPort)
        $stream = $tcp.GetStream()
        $ssl = New-Object Net.Security.SslStream($stream, $true, $null, $null)
        $ssl.AuthenticateAsClient($IMAPServer)
        
        $writer = New-Object IO.StreamWriter($ssl)
        $reader = New-Object IO.StreamReader($ssl)

        $writer.AutoFlush = $true
        $writer.WriteLine("a1 LOGIN $Username $Password")
        $response = $reader.ReadLine()
        
        $writer.WriteLine("a2 SEARCH FROM $Domain")
        $response = $reader.ReadLine()
        
        $writer.WriteLine("a3 LOGOUT")
        $response = $reader.ReadLine()

        $tcp.Close()
        
        if ($response -match "\* SEARCH (\d+)") {
            return $matches[1]
        }
        return $null
    } catch {
        return $null
    }
}

Write-Host "Monitor de correos iniciado..." -ForegroundColor Cyan
Write-Host "Buscando correos de: $Domain" -ForegroundColor Yellow

$lastEmails = Check-Emails

while ($true) {
    Start-Sleep -Seconds $CheckInterval
    $currentEmails = Check-Emails
    
    if ($currentEmails -and $currentEmails -ne $lastEmails) {
        $wshell = New-Object -ComObject WScript.Shell
        $wshell.Popup("Nuevo correo de $Domain!", 10, "Notificación", 64)
        Write-Host "¡NUEVO CORREO DETECTADO!" -ForegroundColor Green
    }
    
    $lastEmails = $currentEmails
}