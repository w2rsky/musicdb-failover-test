<p align="center">
  <img src="./assets/banner.svg" alt="MusicDB Failover Test banner" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/PostgreSQL-16-336791?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Docker-Compose-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker Compose">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Failover-Test-22C55E?style=for-the-badge" alt="Failover Test">
</p>

<p align="center">
  <b>EN</b> PostgreSQL failover simulation for a music streaming DBMS  
  <br>
  <b>RU</b> Симуляция отказоустойчивости PostgreSQL для СУБД музыкального стриминга
</p>

---

## Language / Язык

- [English](#english)
- [Русский](#русский)

---

# English

## Project Theme

**Testing DBMS node failure in a music streaming system**

This project demonstrates how a PostgreSQL cluster can continue working after the main database node fails.

The system simulates a simplified music streaming platform where users listen to tracks, and the database stores:

- listeners;
- artists;
- tracks;
- playback events;
- synthetic workload records.

The main goal is to test **fault tolerance**, **replication**, and **safe standby promotion**.

---

## Mission

The mission of this project is to build a small PostgreSQL high-availability laboratory environment with three logical nodes:

| Node | Role | Purpose |
|---|---|---|
| `postgres-master` | Primary DB node | Accepts reads and writes |
| `postgres-standby` | Replica node | Receives WAL data from master |
| `pg_arbiter` | Witness node | Confirms whether failover is safe |

When the master node becomes unavailable, the standby should be promoted only if the arbiter also confirms that the master is unreachable.

This prevents a dangerous situation called **split-brain**, where two nodes become writable masters at the same time.

---

## Architecture

```mermaid
flowchart LR
    C[Client / Workload Generator] --> M[(PostgreSQL Master)]
    M -- WAL Streaming Replication --> S[(PostgreSQL Standby)]
    S -- asks status --> A[Arbiter / Witness]
    A -- confirms master unavailable --> S
    S -- pg_ctl promote --> NM[(New Master)]

    classDef master fill:#0369a1,color:#fff,stroke:#38bdf8,stroke-width:2px;
    classDef standby fill:#4c1d95,color:#fff,stroke:#a78bfa,stroke-width:2px;
    classDef arbiter fill:#065f46,color:#fff,stroke:#34d399,stroke-width:2px;
    classDef client fill:#334155,color:#fff,stroke:#94a3b8,stroke-width:2px;

    class M,NM master;
    class S standby;
    class A arbiter;
    class C client;
