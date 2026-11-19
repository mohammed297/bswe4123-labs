# Lab Assignment 1: Is the Service Up, Slow or Down?

## Overview

This lab demonstrates how to monitor three local HTTP service instances and classify each service as:

- **UP** — The service responds successfully within the expected response time.
- **SLOW** — The service responds, but its response time exceeds the configured threshold.
- **SUSPECT** — A health check has failed, but the configured number of consecutive failures has not yet been reached.
- **DOWN** — The service has failed the configured number of consecutive health checks.

The monitor checks three local service instances on ports `8001`, `8002`, and `8003` through their `/health` endpoints.

## Project Files

| File | Description |
|---|---|
| `service.py` | Runs a service instance and provides a `/health` endpoint that returns the service status and uptime. It also supports an optional artificial delay. |
| `monitor.py` | Checks all three service instances every two seconds and reports their status and response time. |

## Requirements

- Python 3
- `httpx`

Install the dependency:

```bash
python -m pip install httpx
```

---

## 1. Run the Three Service Instances

Open three separate terminals in the project directory and run one command in each terminal.

**Terminal 1**

```bash
python service.py --port 8001
```

**Terminal 2**

```bash
python service.py --port 8002
```

**Terminal 3**

```bash
python service.py --port 8003
```

Each instance exposes a health-check endpoint:

- `http://127.0.0.1:8001/health`
- `http://127.0.0.1:8002/health`
- `http://127.0.0.1:8003/health`

The endpoint returns JSON containing the service status and uptime in seconds. An example response is:

```json
{
  "status": "ok",
  "uptime_seconds": 12.34
}
```

**Service instance logs**

![Port 8001 service log](Screenshot%202026-11-19%20163853.jpg)

![Port 8002 service log](Screenshot%202026-11-19%20163903.jpg)

![Port 8003 service log](Screenshot%202026-11-19%20163911.jpg)

---

## 2. Run the Monitor — Normal Operation

Open another terminal in the project directory and run:

```bash
python monitor.py
```

The monitor checks the three services every two seconds and displays each service's status and response time.

### Normal Operation — All Services UP

**Captured monitor output:**

```text
[15:53:55] 8001: UP (8 ms) | 8002: UP (4 ms) | 8003: UP (3 ms)
[15:53:57] 8001: UP (3 ms) | 8002: UP (21 ms) | 8003: UP (16 ms)
[15:53:59] 8001: UP (3 ms) | 8002: UP (27 ms) | 8003: UP (16 ms)
[15:54:01] 8001: UP (3 ms) | 8002: UP (3 ms) | 8003: UP (23 ms)
[15:54:03] 8001: UP (23 ms) | 8002: UP (15 ms) | 8003: UP (16 ms)
```

**Observation:** All three service instances responded successfully with low response times, well below the configured slow-response threshold.

![All three services UP](Screenshot%202026-11-19%20163924.jpg)

---

## 3. Simulate a DOWN Service and Recovery

Stop the service running on port `8001` by pressing `Ctrl+C` in its terminal. Keep the monitor running and allow it to perform at least three checks.

**Captured monitor output:**

```text
[16:09:19] 8001: SUSPECT (1/3 failures) | 8002: UP (18 ms) | 8003: UP (16 ms)
[16:09:21] 8001: SUSPECT (2/3 failures) | 8002: UP (4 ms) | 8003: UP (3 ms)
[16:09:23] 8001: DOWN (3 consecutive failures) | 8002: UP (18 ms) | 8003: UP (15 ms)
```

After restarting the service on port `8001` with the command below, the monitor detected a successful response and reported the service as **UP** again.

```bash
python service.py --port 8001
```

**Observation:** The monitor did not report the service as DOWN after a single failed request. It first reported SUSPECT and waited until three consecutive checks had failed.

![Port 8001 transitioning to DOWN](Screenshot%202026-11-19%20163936.jpg)

![Port 8001 recovery and Port 8002 slow response](Screenshot%202026-11-19%20163946.jpg)

---

## 4. Simulate a SLOW Service and Restore Normal Speed

Stop the normal service on port `8002`, then restart it with an artificial delay of `0.8` seconds:

```bash
python service.py --port 8002 --delay 0.8
```

**Captured monitor output:**

```text
[16:23:45] 8001: UP (28 ms) | 8002: SUSPECT (1/3 failures) | 8003: UP (17 ms)
[16:23:47] 8001: UP (3 ms) | 8002: SLOW (805 ms) | 8003: UP (12 ms)
[16:23:49] 8001: UP (25 ms) | 8002: SLOW (817 ms) | 8003: UP (14 ms)
```

The response time of approximately `800 ms` is above the configured `500 ms` slow threshold but below the `1.0 second` request timeout. Therefore, the service is reachable and is reported as **SLOW**, not DOWN.

After stopping the delayed process, restart port `8002` without the delay:

```bash
python service.py --port 8002
```

The service should return to the normal **UP** state with a low response time.

**Screenshot evidence:** The combined monitor screenshot above shows the slow response of port `8002`. The following screenshot shows port `8002` running normally again.

![Port 8002 restarted and back to normal operation](Screenshot%202026-11-19%20163903.jpg)

---

## 5. Failure Detection Settings, Gains, and Trade-offs

The monitor uses the following settings:

| Setting | Value | Purpose |
|---|---:|---|
| Check interval | 2 seconds | Time between monitoring rounds. |
| Request timeout | 1 second | Maximum time to wait for a health-check response before counting the check as failed. |
| Slow threshold | 500 ms | A successful response taking longer than this threshold is reported as SLOW. |
| Consecutive failures | 3 | Number of failed checks required before reporting DOWN. |

### Why Use a 1-Second Timeout?

A timeout prevents the monitor from waiting indefinitely for an unresponsive service. A relatively short timeout helps detect failures sooner. However, a timeout that is too short could classify a temporarily delayed service as failed.

### Why Require 3 Consecutive Failures?

Requiring three consecutive failures reduces the chance of reporting DOWN because of one temporary network issue or brief interruption. The trade-off is that failure detection takes longer than it would with a single failed check.

The monitor reports **SUSPECT** after the first and second consecutive failures, then reports **DOWN** after the third. A successful check resets the consecutive-failure count and returns the service to **UP** or **SLOW**, depending on its response time.

---

## Conclusion

This experiment demonstrated the difference between a healthy, slow, and unavailable service. It also showed how consecutive-failure detection can reduce false DOWN alerts while still detecting a service that remains unavailable.