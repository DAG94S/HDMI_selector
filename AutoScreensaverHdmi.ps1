param(
    [int]$PollSeconds = 5,
    [int]$ScreensaverTimeoutSeconds = 60,
    [switch]$Once,
    [switch]$Status
)

$ErrorActionPreference = 'Stop'

$desktopKey = 'HKCU:\Control Panel\Desktop'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class DisplayConfigReader
{
    private const int QDC_ONLY_ACTIVE_PATHS = 0x00000002;
    private const int ERROR_SUCCESS = 0;

    [StructLayout(LayoutKind.Sequential)]
    public struct LUID
    {
        public uint LowPart;
        public int HighPart;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct DISPLAYCONFIG_RATIONAL
    {
        public uint Numerator;
        public uint Denominator;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct DISPLAYCONFIG_2DREGION
    {
        public uint cx;
        public uint cy;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct DISPLAYCONFIG_VIDEO_SIGNAL_INFO
    {
        public ulong pixelRate;
        public DISPLAYCONFIG_RATIONAL hSyncFreq;
        public DISPLAYCONFIG_RATIONAL vSyncFreq;
        public DISPLAYCONFIG_2DREGION activeSize;
        public DISPLAYCONFIG_2DREGION totalSize;
        public uint videoStandard;
        public uint scanLineOrdering;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct DISPLAYCONFIG_PATH_SOURCE_INFO
    {
        public LUID adapterId;
        public uint id;
        public uint modeInfoIdx;
        public uint statusFlags;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct DISPLAYCONFIG_PATH_TARGET_INFO
    {
        public LUID adapterId;
        public uint id;
        public uint modeInfoIdx;
        public int outputTechnology;
        public uint rotation;
        public uint scaling;
        public DISPLAYCONFIG_RATIONAL refreshRate;
        public uint scanLineOrdering;
        public bool targetAvailable;
        public uint statusFlags;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct DISPLAYCONFIG_PATH_INFO
    {
        public DISPLAYCONFIG_PATH_SOURCE_INFO sourceInfo;
        public DISPLAYCONFIG_PATH_TARGET_INFO targetInfo;
        public uint flags;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct DISPLAYCONFIG_SOURCE_MODE
    {
        public uint width;
        public uint height;
        public uint pixelFormat;
        public POINTL position;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct POINTL
    {
        public int x;
        public int y;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct DISPLAYCONFIG_TARGET_MODE
    {
        public DISPLAYCONFIG_VIDEO_SIGNAL_INFO targetVideoSignalInfo;
    }

    [StructLayout(LayoutKind.Explicit)]
    public struct DISPLAYCONFIG_MODE_INFO_UNION
    {
        [FieldOffset(0)]
        public DISPLAYCONFIG_TARGET_MODE targetMode;
        [FieldOffset(0)]
        public DISPLAYCONFIG_SOURCE_MODE sourceMode;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct DISPLAYCONFIG_MODE_INFO
    {
        public uint infoType;
        public uint id;
        public LUID adapterId;
        public DISPLAYCONFIG_MODE_INFO_UNION modeInfo;
    }

    [DllImport("user32.dll")]
    private static extern int GetDisplayConfigBufferSizes(
        uint flags,
        out uint numPathArrayElements,
        out uint numModeInfoArrayElements);

    [DllImport("user32.dll")]
    private static extern int QueryDisplayConfig(
        uint flags,
        ref uint numPathArrayElements,
        [Out] DISPLAYCONFIG_PATH_INFO[] pathArray,
        ref uint numModeInfoArrayElements,
        [Out] DISPLAYCONFIG_MODE_INFO[] modeInfoArray,
        IntPtr currentTopologyId);

    public static int[] GetActiveOutputTechnologies()
    {
        uint pathCount;
        uint modeCount;
        int result = GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, out pathCount, out modeCount);
        if (result != ERROR_SUCCESS)
        {
            throw new InvalidOperationException("GetDisplayConfigBufferSizes failed: " + result);
        }

        DISPLAYCONFIG_PATH_INFO[] paths = new DISPLAYCONFIG_PATH_INFO[pathCount];
        DISPLAYCONFIG_MODE_INFO[] modes = new DISPLAYCONFIG_MODE_INFO[modeCount];
        result = QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, ref pathCount, paths, ref modeCount, modes, IntPtr.Zero);
        if (result != ERROR_SUCCESS)
        {
            throw new InvalidOperationException("QueryDisplayConfig failed: " + result);
        }

        int[] outputTechnologies = new int[pathCount];
        for (int i = 0; i < pathCount; i++)
        {
            outputTechnologies[i] = paths[i].targetInfo.outputTechnology;
        }

        return outputTechnologies;
    }
}
'@

function Get-OutputTechnologyName {
    param([int]$Value)

    switch ($Value) {
        -1 { 'Other' }
        0 { 'HD15/VGA' }
        1 { 'S-Video' }
        2 { 'Composite' }
        3 { 'Component' }
        4 { 'DVI' }
        5 { 'HDMI' }
        6 { 'Internal/Laptop' }
        8 { 'D-JPN' }
        9 { 'SDI' }
        10 { 'DisplayPort externo' }
        11 { 'DisplayPort interno' }
        12 { 'UDI externo' }
        13 { 'UDI interno' }
        14 { 'SDTV dongle' }
        15 { 'Miracast' }
        16 { 'Indirect wired' }
        17 { 'Indirect virtual' }
        18 { 'DisplayPort USB tunneling' }
        -2147483648 { 'Internal/Laptop' }
        default { "Desconocido ($Value)" }
    }
}

function Get-DisplayState {
    $technologies = [DisplayConfigReader]::GetActiveOutputTechnologies()
    $names = @($technologies | ForEach-Object { Get-OutputTechnologyName $_ })
    $onlyHdmiActive = ($technologies.Count -eq 1 -and $technologies[0] -eq 5)

    [pscustomobject]@{
        ActiveOutputTechnologies = $technologies
        ActiveDisplays = $names
        OnlyHdmiActive = $onlyHdmiActive
    }
}

function Set-ScreensaverDisabled {
    Set-ItemProperty -Path $desktopKey -Name ScreenSaveActive -Value '0'
}

function Set-ScreensaverOneMinute {
    Set-ItemProperty -Path $desktopKey -Name ScreenSaveActive -Value '1'
    Set-ItemProperty -Path $desktopKey -Name ScreenSaveTimeOut -Value ([string]$ScreensaverTimeoutSeconds)
}

function Apply-State {
    $displayState = Get-DisplayState

    if ($displayState.OnlyHdmiActive) {
        Set-ScreensaverDisabled
        $screensaverState = 'desactivado'
    }
    else {
        Set-ScreensaverOneMinute
        $screensaverState = "activado a $ScreensaverTimeoutSeconds segundos"
    }

    [pscustomobject]@{
        Time = Get-Date
        ActiveDisplays = ($displayState.ActiveDisplays -join ', ')
        OnlyHdmiActive = $displayState.OnlyHdmiActive
        Screensaver = $screensaverState
    }
}

if ($Status) {
    $state = Get-DisplayState
    $current = Get-ItemProperty -Path $desktopKey

    [pscustomobject]@{
        ActiveDisplays = ($state.ActiveDisplays -join ', ')
        OnlyHdmiActive = $state.OnlyHdmiActive
        ScreenSaveActive = $current.ScreenSaveActive
        ScreenSaveTimeOut = $current.ScreenSaveTimeOut
        ScrnSaveExe = $current.'SCRNSAVE.EXE'
    }
    exit
}

if ($Once) {
    Apply-State
    exit
}

$lastSignature = $null
while ($true) {
    try {
        $result = Apply-State
        $signature = "$($result.ActiveDisplays)|$($result.Screensaver)"
        if ($signature -ne $lastSignature) {
            $result
            $lastSignature = $signature
        }
    }
    catch {
        Write-Warning $_.Exception.Message
    }

    Start-Sleep -Seconds $PollSeconds
}
