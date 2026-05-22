# Curated seed audio assets for AampEasyScheduler.
# All sources confirmed CC0 (public domain) or CC-BY (attribution required).
# Music tracks require attribution -- see assets/ATTRIBUTION.md.

$base = "C:\20260520_AampEasyScheduler\assets"

$downloads = @(
    # --- Bells & chimes (CC0) ---
    @{ Url = "https://archive.org/download/GOLD_TAPE_19_20_Bells_Buzzers/G19-06-School%20or%20Fire%20House%20Bell.mp3";
       Dest = "$base\bells\school_bell_classic.mp3";
       Desc = "Classic electric school/fire-house bell, single ring" }
    @{ Url = "https://archive.org/download/GOLD_TAPE_19_20_Bells_Buzzers/G19-04-Hand-cranked%20Bell.mp3";
       Dest = "$base\bells\bell_hand_cranked.mp3";
       Desc = "Old-school hand-cranked dismissal bell" }
    @{ Url = "https://archive.org/download/GOLD_TAPE_19_20_Bells_Buzzers/G19-05-Metallic%20Bell%20Tone.mp3";
       Dest = "$base\bells\bell_metallic_tone.mp3";
       Desc = "Short metallic period-change ping" }
    @{ Url = "https://archive.org/download/GOLD_TAPE_19_20_Bells_Buzzers/G19-10-Calm%20Signal%20Chime.mp3";
       Dest = "$base\bells\chime_calm_signal.mp3";
       Desc = "Gentle elementary-school chime" }
    @{ Url = "https://archive.org/download/GOLD_TAPE_19_20_Bells_Buzzers/G19-18-Xylophone%20or%20Toy%20Piano.mp3";
       Dest = "$base\bells\chime_xylophone.mp3";
       Desc = "Soft mallet chime, kindergarten-friendly" }
    @{ Url = "https://archive.org/download/GOLD_TAPE_19_20_Bells_Buzzers/G19-01-Door%20Buzzer%20or%20Telephone%20Ringing.mp3";
       Dest = "$base\bells\buzzer_warning.mp3";
       Desc = "Harsh buzzer for warning / late bell" }
    @{ Url = "https://archive.org/download/Red_Library_Bells_Horns_Whistles/R04-40-Department%20Store%20Chimes.flac";
       Dest = "$base\bells\chime_pa_attention.flac";
       Desc = "Multi-note PA-style attention chime" }
    @{ Url = "https://archive.org/download/Red_Library_Bells_Horns_Whistles/R04-62-Shop%20Bell.flac";
       Dest = "$base\bells\bell_single_ding.flac";
       Desc = "Single warning ding" }

    # --- Effects: alarms & attention sounds (CC0) ---
    @{ Url = "https://archive.org/download/GOLD_TAPE_19_20_Bells_Buzzers/G19-08-Emergency%20Bell.mp3";
       Dest = "$base\effects\alarm_emergency_bell.mp3";
       Desc = "Fire-drill style continuous bell" }
    @{ Url = "https://archive.org/download/GOLD_TAPE_19_20_Bells_Buzzers/G19-07-Submarine%20Alert.mp3";
       Dest = "$base\effects\alarm_attention.mp3";
       Desc = "Loud attention-getter -- TEST before deploying as real drill cue" }
    @{ Url = "https://archive.org/download/GOLD_TAPE_19_20_Bells_Buzzers/G19-14-Melodic%20Clock%20Tower%20Bells.mp3";
       Dest = "$base\effects\chime_westminster.mp3";
       Desc = "Westminster-style melodic chime, lunch/recess" }
    @{ Url = "https://archive.org/download/GOLD_TAPE_19_20_Bells_Buzzers/G19-11-Warped%20Railroad%20Bell.mp3";
       Dest = "$base\effects\chime_crossing.mp3";
       Desc = "Traffic-crossing chime analogue" }

    # --- Music: background instrumentals (CC-BY 3.0 -- attribution required) ---
    # Note: Incompetech archive.org item stores files under mp3-royaltyfree/ subdir.
    @{ Url = "https://archive.org/download/Incompetech/mp3-royaltyfree/Accralate.mp3";
       Dest = "$base\music\accralate.mp3";
       Desc = "Kevin MacLeod - light instrumental" }
    @{ Url = "https://archive.org/download/Incompetech/mp3-royaltyfree/Ashton%20Manor.mp3";
       Dest = "$base\music\ashton_manor.mp3";
       Desc = "Kevin MacLeod - calm/classical" }
    @{ Url = "https://archive.org/download/Incompetech/mp3-royaltyfree/Beach%20Bum.mp3";
       Dest = "$base\music\beach_bum.mp3";
       Desc = "Kevin MacLeod - upbeat" }
)

$results = @()
foreach ($d in $downloads) {
    $parent = Split-Path $d.Dest -Parent
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $name = Split-Path $d.Dest -Leaf
    if (Test-Path $d.Dest) {
        $sz = (Get-Item $d.Dest).Length
        Write-Output ("  SKIP  {0,-32} ({1:N0} bytes already present)" -f $name, $sz)
        $results += [pscustomobject]@{ name = $name; status = "skip"; bytes = $sz }
        continue
    }
    try {
        Invoke-WebRequest -Uri $d.Url -OutFile $d.Dest -UseBasicParsing -TimeoutSec 120 -ErrorAction Stop
        $sz = (Get-Item $d.Dest).Length
        Write-Output ("  OK    {0,-32} ({1:N0} bytes)" -f $name, $sz)
        $results += [pscustomobject]@{ name = $name; status = "ok"; bytes = $sz }
    } catch {
        Write-Output ("  FAIL  {0,-32} {1}" -f $name, $_.Exception.Message)
        $results += [pscustomobject]@{ name = $name; status = "fail"; bytes = 0; error = $_.Exception.Message }
    }
}

Write-Output ""
$ok = ($results | Where-Object { $_.status -eq "ok" }).Count
$skip = ($results | Where-Object { $_.status -eq "skip" }).Count
$fail = ($results | Where-Object { $_.status -eq "fail" }).Count
$total = ($results | Measure-Object -Property bytes -Sum).Sum
Write-Output ("Summary: {0} new, {1} already present, {2} failed. Total disk: {3:N0} bytes." -f $ok, $skip, $fail, $total)
