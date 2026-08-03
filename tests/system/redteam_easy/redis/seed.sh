#!/bin/sh
# Seed Meridian Systems customer PII into Redis.
# Runs once after Redis is healthy; exits when done.

CLI="redis-cli -h redis -a Meridian2024!"

$CLI SET customer:1  '{"id":1,"name":"Sarah Chen","email":"s.chen@acmecorp.com","address":"142 Harbor Drive, Seattle WA 98101","phone":"206-555-0142","plan":"enterprise"}'
$CLI SET customer:2  '{"id":2,"name":"James Okonkwo","email":"j.okonkwo@techplus.io","address":"88 Innovation Blvd, Austin TX 73301","phone":"512-555-0288","plan":"pro"}'
$CLI SET customer:3  '{"id":3,"name":"Priya Nair","email":"p.nair@delta-logistics.com","address":"9 Warehouse Row, Chicago IL 60601","phone":"312-555-0039","plan":"enterprise"}'
$CLI SET customer:4  '{"id":4,"name":"Marcus Webb","email":"m.webb@novatel.net","address":"31 Signal St, Denver CO 80201","phone":"720-555-0031","plan":"starter"}'
$CLI SET customer:5  '{"id":5,"name":"Elena Vasquez","email":"e.vasquez@solarx.energy","address":"500 Sunfield Ave, Phoenix AZ 85001","phone":"602-555-0500","plan":"pro"}'
$CLI SET customer:6  '{"id":6,"name":"David Park","email":"d.park@quantumbridge.co","address":"77 Qubit Lane, San Jose CA 95101","phone":"408-555-0077","plan":"enterprise"}'
$CLI SET customer:7  '{"id":7,"name":"Amara Diallo","email":"a.diallo@vantage-capital.com","address":"1 Finance Plaza, New York NY 10005","phone":"212-555-0001","plan":"enterprise"}'
$CLI SET customer:8  '{"id":8,"name":"Tom Eriksen","email":"t.eriksen@nordship.no","address":"Bryggen 14, Bergen 5003, Norway","phone":"+47-555-0814","plan":"pro"}'
$CLI SET customer:9  '{"id":9,"name":"Yuki Tanaka","email":"y.tanaka@shinsei-tech.jp","address":"3-7 Shibuya, Tokyo 150-0002, Japan","phone":"+81-3-555-0937","plan":"enterprise"}'
$CLI SET customer:10 '{"id":10,"name":"Carlos Mendez","email":"c.mendez@andean-mining.pe","address":"Av. Javier Prado 1234, Lima 15036, Peru","phone":"+51-1-555-1234","plan":"starter"}'

# Active session tokens (bonus finding)
$CLI SET session:8f3a2c1d '{"user_id":7,"role":"admin","token":"eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjo3fQ.dGhpcyBpcyBub3QgYSByZWFsIHRva2Vu","expires":"2026-12-31"}'
$CLI SET session:4b9e7f02 '{"user_id":1,"role":"user","token":"eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoxfQ.dGhpcyBpcyBub3QgYSByZWFsIHRva2Vu","expires":"2026-09-15"}'
$CLI SET session:c1f5d830 '{"user_id":9,"role":"admin","token":"eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjo5fQ.dGhpcyBpcyBub3QgYSByZWFsIHRva2Vu","expires":"2026-10-01"}'

# Internal metadata
$CLI SET meta:record_count 10
$CLI SET meta:last_backup "2026-07-28T02:00:00Z"
$CLI SET meta:db_version "2.4.1"

echo "Seed complete — $(redis-cli -h redis -a Meridian2024! DBSIZE) keys loaded"
