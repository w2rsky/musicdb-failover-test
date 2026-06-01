# MusicDB Failover Test

Theme: **Testing DB node failure in a music streaming DBMS**

This project demonstrates PostgreSQL fault tolerance using:

- PostgreSQL Master node
- PostgreSQL Standby replica
- Arbiter node
- Python failover agent
- Synthetic music streaming workload

## Topology

```text
Client / workload
       |
       v
PostgreSQL Master  --->  PostgreSQL Standby
       |                         |
       |                         v
       +------ Arbiter <---------+# musicdb-failover-test
