# .\scripts\chaos.ps1 errors
#   errors -> HighErrorRate      slow -> HighLatencyP95       hang -> EndpointDown
#   leak   -> MemoryNearLimit    oom  -> ContainerOOMKilled   cpu  -> ContainerCPUThrottled
#   crash  -> ContainerRestarted db-down/db-up -> DependencyDown
#   app-down/app-up -> ServiceDown                            reset, status
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("errors", "slow", "hang", "leak", "oom", "cpu", "crash", "db-down", "db-up", "app-down", "app-up", "reset", "status")]
    [string]$Fault,
    [string]$Url = "http://localhost:8100"
)

function Invoke-Chaos($action, $body) {
    Invoke-RestMethod -Method Post -Uri "$Url/api/chaos/$action" -ContentType "application/json" `
        -Body ($body | ConvertTo-Json) | ConvertTo-Json -Depth 4
}

switch ($Fault) {
    "errors"   { Invoke-Chaos "errors" @{ rate = 0.5 } }
    "slow"     { Invoke-Chaos "latency" @{ ms = 1500 } }
    "hang"     { Invoke-Chaos "latency" @{ ms = 3000 } }
    "leak"     { Invoke-Chaos "leak" @{ mb_per_sec = 5; max_mb = 170 } }
    "oom"      { Invoke-Chaos "oom" @{ mb_per_sec = 40 } }
    "cpu"      { Invoke-Chaos "cpu" @{ seconds = 120 } }
    "crash"    { Invoke-Chaos "crash" @{} }
    "reset"    { Invoke-Chaos "reset" @{} }
    "db-down"  { docker stop ia2-redis; "Redis stopped. DependencyDown should arrive in about 30 s." }
    "db-up"    { docker start ia2-redis; "Redis started. The alert resolves within about a minute." }
    "app-down" { docker stop ia2-shop-api; "OrderFlow stopped. ServiceDown should arrive in about 45 s." }
    "app-up"   { docker start ia2-shop-api; "OrderFlow started." }
    "status"   { Invoke-RestMethod "$Url/api/chaos" | ConvertTo-Json }
}
