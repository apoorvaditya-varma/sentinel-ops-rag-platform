"""The subject areas this platform accepts documents for (10 domains).

Each domain's `description` and `examples` are embedded as prototypes for the
local relevance check and are also shown to the LLM classifier, so adding a
new subject area is a matter of adding one entry here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Domain:
    key: str
    label: str
    description: str
    examples: tuple[str, ...]
    keywords: tuple[str, ...]


DOMAINS: tuple[Domain, ...] = (
    Domain(
        key="devops",
        label="DevOps & SRE",
        description="Software delivery and operations: CI/CD pipelines, deployments, releases, "
        "containers, Kubernetes, infrastructure as code, monitoring, on-call, runbooks and postmortems.",
        examples=(
            "Runbook: the pod is in CrashLoopBackOff; check kubectl logs and roll back the deployment.",
            "The CI/CD pipeline builds the Docker image, runs tests and deploys to production with a canary.",
            "Postmortem: the release caused elevated error rates and latency; action items and owners.",
            "Helm chart values, Terraform modules and Ansible playbooks for the platform team.",
        ),
        keywords=(
            "kubernetes", "kubectl", "apiversion", "namespace", "replicas", "liveness", "docker", "container", "helm", "terraform", "ansible", "ci/cd",
            "pipeline", "jenkins", "github actions", "gitlab", "argocd", "deployment", "rollback",
            "canary", "release", "runbook", "postmortem", "on-call", "sre", "slo", "sla", "latency",
            "prometheus", "grafana", "observability", "pod", "cluster", "microservice", "incident",
        ),
    ),
    Domain(
        key="governance",
        label="IT governance, compliance & code security",
        description="IT and information-security governance, risk and compliance: policies, standards, "
        "audits, controls, ISO 27001, SOC 2, PCI DSS, NIST, GDPR, secure coding, code review, "
        "application security testing and software supply chain.",
        examples=(
            "Information security policy: all administrator accounts must use phishing-resistant MFA.",
            "SOC 2 audit evidence for change management and access review controls.",
            "Secure coding standard: validate input, use parameterised queries, never commit secrets.",
            "Risk register entry with likelihood, impact, owner and mitigation due date.",
        ),
        keywords=(
            "policy", "standard", "compliance", "audit", "control", "iso 27001", "soc 2", "pci dss",
            "nist", "gdpr", "hipaa", "risk register", "governance", "exception", "secure coding",
            "code review", "sast", "dast", "sca", "sbom", "owasp", "dependency", "least privilege",
            "data classification", "retention", "attestation", "evidence", "personal data",
            "data subject", "dpo", "data protection", "privacy",
        ),
    ),
    Domain(
        key="cloudops",
        label="CloudOps",
        description="Operating public and private cloud: AWS, Azure and GCP resources, accounts, "
        "accounts, IAM, compute, storage, managed services, landing zones and cloud security posture.",
        examples=(
            "AWS account baseline: CloudTrail enabled, S3 buckets private, IAM roles instead of users.",
            "Azure subscription policies, resource groups and managed identities for the AKS cluster.",
            "GCP VPC peering and firewall rules for the production project.",
            "Landing zone design: account structure, service control policies and centralised logging.",
        ),
        keywords=(
            "aws", "azure", "gcp", "google cloud", "ec2", "s3", "lambda", "cloudtrail", "cloudwatch",
            "iam", "vpc", "subnet", "load balancer", "region", "availability zone", "eks", "aks",
            "gke", "rds", "landing zone", "cspm", "terraform state", "cloudformation", "arm template",
        ),
    ),
    Domain(
        key="secops",
        label="SecOps",
        description="Security operations: SOC, SIEM alerts, threat detection, incident response, "
        "threat intelligence, MITRE ATT&CK, vulnerability management and forensics.",
        examples=(
            "SIEM alert: brute force detected, more than 20 failed logins from one IP in 5 minutes.",
            "Incident response plan: containment, eradication, recovery and evidence preservation.",
            "Vulnerability scan findings with CVE, CVSS score, severity and remediation due date.",
            "Threat intelligence report mapping attacker techniques to MITRE ATT&CK.",
        ),
        keywords=(
            "siem", "soc", "alert", "detection", "threat", "mitre", "att&ck", "cve", "cvss",
            "vulnerability", "exploit", "malware", "ransomware", "phishing", "ioc", "forensic",
            "edr", "xdr", "triage", "containment", "eradication", "brute force", "kev", "patch",
            "lateral movement", "c2", "beaconing", "401", "403", "failed login", "user-agent",
        ),
    ),
    Domain(
        key="itsecurity",
        label="IT security",
        description="Protecting corporate IT: identity and access management, MFA, endpoint and "
        "network security, encryption, secrets management, data protection and security awareness.",
        examples=(
            "Access control: quarterly access reviews and revoking leaver accounts within 4 hours.",
            "Rotate leaked API keys immediately and store secrets in the central vault.",
            "Firewall, VPN and network segmentation standard for office and data centre networks.",
            "Endpoint security baseline: disk encryption, EDR agent, automatic OS patching.",
        ),
        keywords=(
            "mfa", "2fa", "sso", "password", "credential", "access control", "identity",
            "active directory", "okta", "encryption", "tls", "certificate", "firewall", "vpn",
            "endpoint", "antivirus", "secret", "vault", "api key", "token", "privileged",
            "zero trust", "segmentation", "dlp", "security awareness",
        ),
    ),
    Domain(
        key="itsm",
        label="IT service management (ITIL)",
        description="IT service management following ITIL: incident, problem, change and release "
        "management, service requests, CAB approvals, service catalogue, SLAs/OLAs and the CMDB.",
        examples=(
            "Change request: standard change with CAB approval, implementation plan, backout plan and risk rating.",
            "Problem record: recurring outage linked to three incidents, root cause analysis and known-error workaround.",
            "Service desk SLA: P1 tickets responded to within 15 minutes and resolved within 4 hours.",
            "CMDB configuration items, service dependencies and service owners for the payment platform.",
        ),
        keywords=(
            "itil", "itsm", "change request", "change advisory board", "cab", "problem record",
            "known error", "service desk", "service request", "ticket", "servicenow",
            "jira service management", "cmdb", "configuration item", "ola", "p1", "major incident",
            "backout plan", "service catalogue", "service catalog", "request fulfilment",
        ),
    ),
    Domain(
        key="ai_governance",
        label="AI / LLM governance & security",
        description="Governance, risk and security of AI and machine-learning systems: AI policies, "
        "model risk management, LLM security and prompt injection, NIST AI RMF, EU AI Act, "
        "ISO 42001, model cards and MLOps controls.",
        examples=(
            "AI acceptable use policy: employees must not paste confidential data into public generative AI tools.",
            "LLM application threat model covering prompt injection, data leakage and excessive agency.",
            "EU AI Act risk classification of the model, with human oversight and logging requirements.",
            "Model card documenting training data, evaluation results, bias testing and drift monitoring.",
        ),
        keywords=(
            "ai", "artificial intelligence", "machine learning", "llm", "large language model",
            "generative ai", "genai", "model risk", "prompt injection", "jailbreak", "hallucination",
            "nist ai rmf", "eu ai act", "iso 42001", "model card", "bias", "fairness", "drift",
            "mlops", "training data", "red teaming", "responsible ai",
        ),
    ),
    Domain(
        key="finops",
        label="FinOps (cloud cost)",
        description="Cloud financial operations: cloud spend and cost allocation, budgets and cost "
        "anomaly alerts, tagging, rightsizing, reserved instances and savings plans, unit cost "
        "and showback/chargeback of cloud services.",
        examples=(
            "Monthly AWS cost report by account and service with month-over-month change and anomalies.",
            "Rightsizing recommendations: downsize underutilised EC2 instances and delete idle EBS volumes.",
            "Savings plan and reserved instance coverage and utilisation for compute workloads.",
            "Tagging policy for cost allocation: every cloud resource needs cost-centre, owner and environment tags.",
        ),
        keywords=(
            "finops", "cloud cost", "cost explorer", "billing", "cloud spend", "budget alert",
            "cost anomaly", "cost allocation", "chargeback", "showback", "rightsizing",
            "reserved instance", "savings plan", "spot instance", "unit cost", "idle resources",
            "cost and usage report", "azure cost management",
        ),
    ),
    Domain(
        key="resilience",
        label="Business continuity & resilience",
        description="Business continuity and operational resilience: business impact analysis, "
        "disaster recovery plans and tests, backups and restores, RTO/RPO, failover, crisis "
        "management and regulations such as DORA.",
        examples=(
            "Disaster recovery test: failover to the secondary region completed in 2 hours against an RTO of 4 hours.",
            "Business impact analysis ranking critical services by maximum tolerable downtime.",
            "Backup policy: daily immutable backups, 35-day retention and quarterly restore tests.",
            "Crisis management plan: activation criteria, call tree and communication templates.",
        ),
        keywords=(
            "business continuity", "bcp", "disaster recovery", "dr test", "drp", "failover",
            "failback", "rto", "rpo", "backup", "restore", "immutable", "business impact analysis",
            "bia", "crisis management", "call tree", "resilience", "dora", "tabletop exercise",
            "maximum tolerable downtime", "high availability", "redundancy",
        ),
    ),
    Domain(
        key="netops",
        label="Network operations",
        description="Network engineering and operations: routing and switching, firewall rules, VPN, "
        "DNS, DHCP, load balancers, WAN/SD-WAN, network monitoring and network changes.",
        examples=(
            "Firewall rule change: allow TCP 443 from the DMZ load balancer to the application subnet.",
            "BGP session flapping between the edge routers; check interface errors and route advertisements.",
            "DNS migration plan: lower TTLs, move zones to the new provider and validate records.",
            "SD-WAN rollout across branch offices with QoS policies for voice traffic.",
        ),
        keywords=(
            "network", "router", "routing", "switch", "bgp", "ospf", "vlan", "subnet",
            "firewall rule", "acl", "vpn", "dns", "dhcp", "ttl", "nat", "load balancer", "wan",
            "sd-wan", "mpls", "qos", "packet loss", "cisco", "juniper", "palo alto", "netflow", "ipam",
        ),
    ),
)

# Contrastive "not our platform" prototypes: relevance is judged by the margin
# between the best platform domain and the best of these.
OFF_TOPIC_EXAMPLES: tuple[str, ...] = (
    "Human resources: annual leave, payroll, benefits, hiring, onboarding and performance reviews.",
    "Finance and accounting: invoices, expense reports, budgets, revenue and sales figures by region.",
    "Sales and marketing: campaigns, leads, customers, branding, advertising and webinars.",
    "Sports news: football match report, goals, players, league table and transfers.",
    "Cooking and food: recipes, ingredients, baking times and restaurant reviews.",
    "Health and medicine: patients, symptoms, diagnosis, medication and treatment.",
    "Corporate ethics and conduct: gifts, conflicts of interest, respectful workplace behaviour.",
    "Travel, lifestyle, fiction, entertainment and general news.",
    "Education: lectures, homework, exams and course syllabus.",
)

DOMAIN_BY_KEY = {domain.key: domain for domain in DOMAINS}
