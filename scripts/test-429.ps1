# 429 + Retry-After 5 -> asteptat: status=delivered, attempts=2,
# doua intrari in /received (429, apoi 200), diferenta arrived_at >= 5 secunde
curl.exe -s -X DELETE http://localhost:9000/received
Invoke-RestMethod -Method Post -Uri http://localhost:9000/control -ContentType "application/json" -Body '{"fail_next": 1, "status_code": 429, "retry_after": 5}' | Out-Null
curl.exe -s -X POST http://localhost:8080/events -H "Content-Type: application/json" --data "@event-429.json"
Start-Sleep 10
curl.exe -s http://localhost:8080/events/evt-429
curl.exe -s http://localhost:9000/received