param([Parameter(Mandatory=$true)][string]$InputPath,[Parameter(Mandatory=$true)][string]$OutputDir,[string]$Backend='wps',[int]$Width=1600,[int]$Height=900)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$progid=if($Backend -eq 'powerpoint'){'PowerPoint.Application'}else{'KWPP.Application'}
$app=New-Object -ComObject $progid
$prior=$app.Presentations.Count
$deck=$null
try {
 $deck=$app.Presentations.Open([IO.Path]::GetFullPath($InputPath),-1,0,0)
 $count=$deck.Slides.Count
 for($i=1;$i -le $count;$i++){
  $target=Join-Path $OutputDir ('{0:D2}.png' -f $i)
  $deck.Slides.Item($i).Export($target,'PNG',$Width,$Height)
 }
 [pscustomobject]@{backend=$Backend;version=[string]$app.Version;slides=$count;width=$Width;height=$Height;window_requested=$false} | ConvertTo-Json -Compress
} finally {
 if($deck){$deck.Close()}
 # Another document may have opened after this renderer started.
 if($prior -eq 0 -and $app.Presentations.Count -eq 0){$app.Quit()}
 if($deck){[void][Runtime.InteropServices.Marshal]::ReleaseComObject($deck)}
 [void][Runtime.InteropServices.Marshal]::ReleaseComObject($app)
}
