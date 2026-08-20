# Distributed Job Queue — Market Research

## Market overview

These tools overlap, but each solves a different problem:

| Technology | Primary purpose | Typical use |
|---|---|---|
| Celery | Application background tasks | Emails, reports, image processing |
| AWS SQS | Managed message queue | Reliable cloud job delivery |
| RabbitMQ | Message routing and brokering | Microservice communication |
| Apache Kafka | Event streaming and history | Analytics and real-time pipelines |
| Temporal | Durable workflow orchestration | Payments, approvals, long-running processes |

## 1. Celery

Celery sends application tasks to workers so slow work runs outside the request cycle.

**Strengths:** simple task model, worker scaling, retries, scheduling, and broad Python framework support.

**Weaknesses:** requires supporting infrastructure and is primarily a task system, not a high-volume event platform or long-running workflow engine.

**Best fit:** SaaS applications, Django systems, data processing, and routine background jobs.

## 2. AWS SQS

SQS is a managed queue. AWS handles the servers, durability, availability, and scaling; applications send and receive messages.

**Strengths:** low operational overhead, durable delivery, visibility timeouts, scaling, and dead-letter queues.

**Weaknesses:** messages have little business meaning; routing and workflow logic must be built by the application. It is also tightly connected to AWS.

**Best fit:** reliable cloud-based jobs and communication between services.

## 3. RabbitMQ

RabbitMQ is a message broker that routes messages through exchanges, bindings, and queues.

**Strengths:** flexible routing, acknowledgements, priorities, and support for one-to-one and broadcast patterns.

**Weaknesses:** more concepts and operational complexity than a basic queue.

**Best fit:** event routing and communication across microservices or enterprise systems.

## 4. Apache Kafka

Kafka is an event-streaming platform that stores an ordered, durable history of events. Consumers can read events independently and replay them.

**Strengths:** very high throughput, event replay, partition-based scaling, and multiple independent consumer groups.

**Weaknesses:** operationally complex and usually excessive for simple background jobs such as emails or PDF generation.

**Best fit:** analytics, data pipelines, monitoring, and real-time event-driven systems.

## 5. Temporal

Temporal coordinates long-running business workflows and remembers progress across failures, retries, timers, and pauses.

**Strengths:** durable execution, workflow state, automatic recovery, timers, and reliable multi-step processes.

**Weaknesses:** more sophisticated than a queue and unnecessary when the requirement is only to execute independent jobs.

**Best fit:** payments, approvals, onboarding, AI agents, and processes that span minutes, days, or weeks.

## What this project should learn

- **Celery:** task and worker execution.
- **SQS:** acknowledgements, visibility timeouts, retries, and dead-letter queues.
- **RabbitMQ:** routing and worker capabilities.
- **Kafka:** independent consumers and event history.
- **Temporal:** explicit workflow state and recovery.

The learning goal is not to copy one product. It is to build a focused hybrid: a task queue with reliable delivery, basic routing, worker coordination, and durable job state.

## References

- [Celery Tasks](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Amazon SQS visibility timeout](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html)
- [Amazon SQS dead-letter queues](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-dead-letter-queues.html)
- [RabbitMQ AMQP model](https://www.rabbitmq.com/tutorials/amqp-concepts)
- [Apache Kafka introduction](https://kafka.apache.org/intro/)
- [Temporal durable execution](https://temporal.io/)
