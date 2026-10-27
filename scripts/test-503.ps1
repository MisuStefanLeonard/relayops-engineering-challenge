# 2 x 503 , apoi succes -> delivered
curl.exe -X DELETE http://localhost:9000/received
Invoke-RestMethod -Method Post -Uri http://localhost:9000/control -ContentType "application/json" -Body '{"fail_next": 2, "status_code": 503}'
curl.exe -s -X POST http://localhost:8080/events -H "Content-Type: application/json" --data "@event_example.json"
Start-Sleep 10
curl.exe -s http://localhost:8080/events/evt-005     #
