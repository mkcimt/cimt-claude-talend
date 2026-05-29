# Microservice log collection — the Log-Server collector-pool saturation trap

> **Layer 2a — universal Talend truth.** Applies to any Talend ESB **data-service microservice deployed on a Remote Engine** (Studio 8.0 / Talend Cloud). Empirically confirmed on Qlik Talend Cloud 8.0.1 against a 2-engine RE cluster; mechanism corroborated by the Qlik docs cited below.

## TL;DR

A microservice's **default** logging ships its log events over a **synchronous, blocking log4j2 `SocketAppender`** to a **per-Remote-Engine Log Server** (`localhost:7788`). The Log Server processes incoming streams with a **fixed worker-thread pool** (`ms.worker.thread.number`). The doc's own words: *"Each microservice deployment occupies one worker thread for logging."* If the number of deployed microservices on an engine exceeds that pool, the Log Server stops draining the surplus sockets → the microservice's TCP send buffer fills → its `synchronized` `TcpSocketManager.write` blocks **forever** (no write timeout) → **every request thread that wants to log blocks on the same monitor** → the whole Jetty worker pool of that one microservice freezes → the API hangs. Restart clears it; it comes back.

## Why it presents as "random, one API, one engine"

These three observations look like they rule out a logging cause. They don't — they're diagnostic *of* it:

- **Only one API at a time.** The blocking monitor is the `org.apache.logging.log4j.core.net.TcpSocketManager` **instance — one per JVM**. Each microservice is its own JVM with its own appender/socket. A stuck write can only freeze threads *inside that one process*. Other APIs are separate JVMs and keep serving.
- **Random which API.** Whichever JVM's TCP send buffer to `localhost:7788` fills first under a logging burst blocks first. Highest-log-volume / unluckiest process loses.
- **Only one engine in a cluster.** The collector host defaults to **`localhost`** — each engine forwards to **its own** Log Server. If engine A's collector pool saturates, only A's microservices block; engine B (its own pool) stays clean.

A *hard-down* shared collector would take out all APIs on all engines at once. Intermittent single-JVM freezes ⇒ **per-connection backpressure against a too-small local pool**, not an outage.

## The default trap

Two values live in **two different files** in `<RemoteEngineInstallationDirectory>/etc`, and nothing reconciles them:

| Property | File | Meaning | Observed default |
|---|---|---|---|
| `ms.running.instance.limit` | `org.talend.ipaas.rt.dsrunner.cfg` | max microservices the engine will run | `20` |
| `ms.worker.thread.number` | `org.talend.ipaas.rt.dsrunner.log4jsocket.collector.cfg` | Log-Server log-processor pool | `10` (seen in the field) |

With "one worker thread per microservice for logging," a pool of 10 cannot service even half of a 20-instance engine — and any real deployment with >10 APIs is **guaranteed** to contend. **Rule of thumb: `ms.worker.thread.number ≥ ms.running.instance.limit`, with headroom.** The Qlik troubleshooting note recommends **50**.

> ⚠️ The `collecting-microservice-logs` page says to edit `org.talend.ipaas.rt.dsrunner.cfg` for `ms.worker.thread.number`. That is **wrong** — the property lives in `org.talend.ipaas.rt.dsrunner.log4jsocket.collector.cfg` (the "log collector properties" file, per `configuring-data-service-runner`). OSGi has its own listener on `7789` with `osgi.worker.thread.number`.

## Diagnosis (read the live JVM, no tools to install)

The microservice runs on the RE's bundled JRE, so `jstack` is usually absent. Use **SIGQUIT** — every JVM dumps all threads to its own stdout/log, no install, non-destructive:

```bash
ps -ef | grep <job_name>        # find the microservice PID
kill -3 <pid>                   # NOT -9; SIGQUIT only dumps
```

In the dump, look for **one** thread holding the log monitor and **N** blocked on it:

- **Holder** — `RUNNABLE`, native socket write, *holds* the monitor:
  ```
  sun.nio.ch.FileDispatcherImpl.write0(Native Method)
  ...
  org.apache.logging.log4j.core.net.TcpSocketManager.writeAndFlush
  org.apache.logging.log4j.core.net.TcpSocketManager.write
  - locked <0x…> (a org.apache.logging.log4j.core.net.TcpSocketManager)
  ...SocketAppender... AbstractLogger.<level>(...)
  ```
- **Victims** — many `qtp…` (Jetty) workers `BLOCKED (on object monitor)`, all `waiting to lock <same 0x…>`, typically at `AbstractLogger.info`. That count ≈ the frozen request pool.

If you see that shape, it's this bug — not the database. (DB sockets that carry `socketTimeout`/`queryTimeout` in their JDBC URL fail fast and look completely different.)

## Fix

1. **Raise the pool.** In `<RE>/etc/org.talend.ipaas.rt.dsrunner.log4jsocket.collector.cfg` set e.g. `ms.worker.thread.number=50` on **every** engine in the cluster.
2. **Restart — no re-deploy.** Per `configuring-data-service-runner`: *"Each property is taken into account when Data Service Runner starts. A property update requires a stop/start of either the Talend Remote Engine or the Data Service Runner."* So a DSR/RE restart suffices; the deployed artifacts are **not** rebuilt or re-published. Restarting bounces the hosted microservices, so in a cluster do it **rolling, one engine at a time** behind the load balancer to keep the APIs reachable.

### Secondary / durable levers

- `ms.log.collection.reconnection.delay` (collector cfg, ms) — how long after a dropped collector connection before reconnect. Field default sometimes raised to `120000` (2 min); the doc default is `10000`. Lower it for faster recovery — it doesn't cause the initial block but lengthens the degraded window.
- **Decouple logging entirely** via `ms.custom.log4j2.conf` (in `dsrunner.cfg`) pointing at a custom log4j2 that wraps the appender in an `AsyncAppender` with `blocking="false"` (drops on full queue instead of freezing request threads). **Trade-off:** when `ms.custom.log4j2.conf` is set, the DSR uses the file *as-is* and **stops auto-configuring collection to Talend Cloud** — you must reproduce the socket/cloud appender yourself, or you lose TMC log visibility.
- Reduce log volume on hot shared code paths (e.g. `FATAL`/`INFO` on a per-request auth helper). `jobLogFatalLevel=true` in the collector cfg routes job FATAL events through this same pool — high-frequency FATAL logging amplifies the contention.

## Source docs (Qlik Talend, Remote Engine User Guide, Cloud)

- Collecting microservice logs (properties, 7788 default, the saturation troubleshooting note): https://help.qlik.com/talend/en-US/remote-engine-user-guide-linux/Cloud/collecting-microservice-logs
- Configuring the Data Service Runner (the five `etc` cfg files; "property update requires a stop/start"): https://help.qlik.com/talend/en-US/remote-engine-user-guide-linux/Cloud/configuring-data-service-runner
- Enabling custom logging (`ms.custom.log4j2.conf`): https://help.qlik.com/talend/en-US/remote-engine-user-guide-linux/Cloud/enabling-custom-logging
- Windows guide carries the same pages under `remote-engine-user-guide-windows/Cloud/...`.
