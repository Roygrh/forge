workspace "Forge" "A governed agent factory" {
    model {
        operator = person "Agent Operator" "Creates and operates agents (AP Manager)"
        approver = person "Approver" "Reviews HITL approvals (AP Analyst)"
        admin = person "Platform Admin" "Publishes, suspends, configures"

        llm = softwareSystem "LLM Providers" "Anthropic (first adapter); swappable" "External"
        erp = softwareSystem "MeridianERP (simulated)" "POs, vendors, receipts, payments" "External"
        intake = softwareSystem "Email Intake (simulated)" "Invoice PDFs arrive here. Modelled, not simulated in this build: invoices are pre-loaded in MeridianERP" "External"

        forge = softwareSystem "Forge" "Governed agent platform" {
            spa = container "Web App" "Catalog, run trace viewer, approval queue, eval suite and publish gate, metrics" "React 18 + Vite + TS"
            api = container "Backend API" "REST API + agent platform" "Python 3.12 + FastAPI" {
                runtimeloop = component "Runtime Loop" "Custom reason/act/observe loop; enforces max_steps and timeout; pauses/resumes across approvals" "Python (ADR-003)"
                dnaregistry = component "DNA Registry" "Validates DNA against the schema; stores and versions definitions; drives lifecycle" "Python"
                toolgateway = component "Tool Gateway" "Tool registry with typed contracts; least-privilege and autonomy policy enforcement; the only path to external systems; fail-closed" "Python"
                llmgateway = component "LLM Adapter Layer" "One complete() contract over provider adapters; enforces token and cost budgets; holds the only copy of API keys" "Python (ADR-005)"
                knowledge = component "Knowledge Retrieval" "Hybrid semantic and lexical retrieval; authority hierarchy; returns citations. Reached only through the Tool Gateway, as a registered tool scoped by the DNA" "Python + pgvector"
                approvals = component "Approval Service" "HITL queue; granular, expiring approvals that cancel and never auto-approve" "Python"
                evalrunner = component "Eval Runner" "Runs the agent over its eval suite; hard publish gate" "Python"
                eventwriter = component "Event Store Writer" "Appends immutable events (no update/delete); serves trace and lifecycle projections" "Python (ADR-008)"
                breaker = component "Circuit Breaker" "Evaluated after every run over a trailing window of events; trips on error or cost thresholds and suspends the version; resume is a recorded admin-only action" "Python"
            }
            db = container "PostgreSQL 16" "Relational + append-only events + pgvector" "PostgreSQL" "Database"
        }

        // People -> Web App
        operator -> spa "Creates and operates agents" "HTTPS"
        approver -> spa "Reviews and decides approvals" "HTTPS"
        admin -> spa "Publishes, suspends, configures" "HTTPS"

        // Container-level
        spa -> api "Calls REST API" "HTTPS/JSON"
        api -> db "Reads/writes state and events" "SQL"
        api -> llm "Requests model completions" "HTTPS/JSON"
        api -> erp "Reads/writes AP data" "HTTPS/JSON"
        api -> intake "Reads invoice PDFs" "HTTPS/JSON"

        // Web App -> components (per screen)
        spa -> dnaregistry "Reads DNA (catalog); publish, suspend, resume (lifecycle)"
        spa -> approvals "List queue; approve/reject"
        spa -> evalrunner "Run suite / publish"
        spa -> eventwriter "Reads run traces and per-agent metrics (projections of events)"

        // Runtime Loop orchestration (component -> component)
        runtimeloop -> dnaregistry "Loads valid DNA definition"
        runtimeloop -> llmgateway "Requests model completions"
        runtimeloop -> toolgateway "Requests tool calls"
        runtimeloop -> approvals "Enqueues requires_approval actions; awaits decision"
        runtimeloop -> eventwriter "Emits trace events (model/tool/rule/decision)"
        runtimeloop -> breaker "Refuses to start a suspended version; re-evaluates the breaker after each run"
        evalrunner -> runtimeloop "Executes agent over eval cases"

        // Components -> external systems (gateway is the only path out)
        llmgateway -> llm "Calls provider (holds API keys)" "HTTPS/JSON"
        toolgateway -> knowledge "Retrieves governed rules and policy chunks (query_rules, search_knowledge) - the only path"
        toolgateway -> erp "Executes AP operations (only path)" "HTTPS/JSON"
        toolgateway -> intake "Reads invoice PDFs (only path)" "HTTPS/JSON"

        // Components -> database
        dnaregistry -> db "Stores/reads versioned DNA" "SQL"
        knowledge -> db "Hybrid search (pgvector + lexical)" "SQL"
        approvals -> db "Persists approval requests/decisions" "SQL"
        eventwriter -> db "Appends events; reads projections" "SQL"
        breaker -> db "Reads recent error/cost events" "SQL"
        evalrunner -> db "Reads suite; writes results" "SQL"
    }
    views {
        systemContext forge "context" {
            include *
            autolayout lr
        }
        container forge "containers" {
            include *
            autolayout lr
        }
        component api "components" {
            include *
            autolayout lr
        }
        styles {
            element "External" {
                background #999999
            }
            element "Database" {
                shape Cylinder
            }
            element "Person" {
                shape Person
            }
        }
    }
}
