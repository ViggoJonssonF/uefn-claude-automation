param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 1962,
    [int]$TimeoutSeconds = 180,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

function Read-ByteWithTimeout {
    param(
        [System.Net.Sockets.NetworkStream]$Stream,
        [datetime]$Deadline
    )

    while ((Get-Date) -lt $Deadline) {
        try {
            return $Stream.ReadByte()
        }
        catch [System.IO.IOException] {
            Start-Sleep -Milliseconds 50
        }
    }

    throw "Timed out waiting for data from UEFN Verse Workflow Server."
}

function Read-ExactBytes {
    param(
        [System.Net.Sockets.NetworkStream]$Stream,
        [int]$Length,
        [datetime]$Deadline
    )

    $Buffer = New-Object byte[] $Length
    $Offset = 0

    while ($Offset -lt $Length) {
        if ((Get-Date) -ge $Deadline) {
            throw "Timed out while reading message body from UEFN Verse Workflow Server."
        }

        try {
            $Read = $Stream.Read($Buffer, $Offset, $Length - $Offset)
            if ($Read -le 0) {
                throw "UEFN Verse Workflow Server closed the connection."
            }
            $Offset += $Read
        }
        catch [System.IO.IOException] {
            Start-Sleep -Milliseconds 50
        }
    }

    return $Buffer
}

function Read-ProtocolMessage {
    param(
        [System.Net.Sockets.NetworkStream]$Stream,
        [datetime]$Deadline
    )

    $HeaderBytes = New-Object System.Collections.Generic.List[byte]

    while ($true) {
        $ByteValue = Read-ByteWithTimeout -Stream $Stream -Deadline $Deadline
        if ($ByteValue -lt 0) {
            throw "UEFN Verse Workflow Server closed the connection."
        }

        $HeaderBytes.Add([byte]$ByteValue)
        $Count = $HeaderBytes.Count

        if (
            $Count -ge 4 -and
            $HeaderBytes[$Count - 4] -eq 13 -and
            $HeaderBytes[$Count - 3] -eq 10 -and
            $HeaderBytes[$Count - 2] -eq 13 -and
            $HeaderBytes[$Count - 1] -eq 10
        ) {
            break
        }
    }

    $Header = [System.Text.Encoding]::UTF8.GetString($HeaderBytes.ToArray())
    $ContentLength = $null

    foreach ($Line in ($Header -split "`r`n")) {
        if ($Line -match "^Content-Length:\s*(\d+)\s*$") {
            $ContentLength = [int]$Matches[1]
            break
        }
    }

    if ($null -eq $ContentLength) {
        throw "UEFN Verse Workflow Server sent a message without Content-Length."
    }

    $BodyBytes = Read-ExactBytes -Stream $Stream -Length $ContentLength -Deadline $Deadline
    $Body = [System.Text.Encoding]::UTF8.GetString($BodyBytes)

    return $Body | ConvertFrom-Json
}

$Client = [System.Net.Sockets.TcpClient]::new()
$Client.ReceiveTimeout = 1000
$Client.SendTimeout = 30000

try {
    $Client.Connect($HostName, $Port)
    $Stream = $Client.GetStream()

    $Request = @{
        seq = 1
        type = 1
        command = "compileProject"
        params = @{}
    } | ConvertTo-Json -Compress

    $RequestBytes = [System.Text.Encoding]::UTF8.GetBytes($Request)
    $Header = "Content-Length: $($RequestBytes.Length)`r`n`r`n"
    $HeaderBytes = [System.Text.Encoding]::UTF8.GetBytes($Header)

    $Stream.Write($HeaderBytes, 0, $HeaderBytes.Length)
    $Stream.Write($RequestBytes, 0, $RequestBytes.Length)

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $Deadline) {
        $Message = Read-ProtocolMessage -Stream $Stream -Deadline $Deadline

        if ($Json) {
            $Message | ConvertTo-Json -Depth 20
        }

        if ($Message.type -eq 0 -and $Message.command -eq "logMessage") {
            Write-Host $Message.params.message
        }

        if ($Message.type -eq 2 -and $Message.seq -eq 1 -and $Message.command -eq "compileProject") {
            if ($null -ne $Message.error) {
                Write-Error $Message.error
                exit 1
            }

            $Result = $Message.result
            Write-Host $Result.message
            Write-Host "Verse build finished: $($Result.numErrors) error(s), $($Result.numWarnings) warning(s)."

            if ($Result.numErrors -gt 0) {
                exit 1
            }

            exit 0
        }
    }

    throw "Timed out waiting for compileProject response from UEFN."
}
finally {
    if ($Stream) {
        $Stream.Close()
    }
    $Client.Close()
}
