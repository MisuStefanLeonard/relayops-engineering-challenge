curl.exe -s -X DELETE http://localhost:9000/received
Invoke-RestMethod -Method Post -Uri http://localhost:9000/control -ContentType "application/json" -Body '{"fail_next": 1, "status_code": 400}' 
curl.exe -s -X POST http://localhost:8080/events -H "Content-Type: application/json" --data "@event-400.json"
Start-Sleep 10
curl.exe -s http://localhost:8080/events/evt-400
curl.exe -s http://localhost:9000/received