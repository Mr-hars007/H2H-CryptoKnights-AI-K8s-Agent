import subprocess

NAMESPACE = "ai-ops"


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip() if result.stdout else result.stderr.strip()


# ---------------- INIT ----------------

def create_namespace():
    return run(["kubectl", "create", "namespace", NAMESPACE])


def deploy_demo():
    cmds = [
        ["kubectl", "create", "deployment", "orders", "--image=nginx", "-n", NAMESPACE],
        ["kubectl", "create", "deployment", "payments", "--image=nginx", "-n", NAMESPACE],
        ["kubectl", "create", "deployment", "gateway", "--image=nginx", "-n", NAMESPACE],
    ]

    outputs = []
    for c in cmds:
        outputs.append(run(c))
    return "\n".join(outputs)


def initialize_cluster():
    out = []
    out.append(create_namespace())
    out.append(deploy_demo())
    return "\n".join(out)


# ---------------- CLEANUP ----------------

def delete_all():
    return run(["kubectl", "delete", "namespace", NAMESPACE])


# ---------------- CHAOS ----------------

def crashloop_orders():
    return run([
        "kubectl", "set", "image",
        "deployment/orders",
        "nginx=invalid-image",
        "-n", NAMESPACE
    ])


def pending_payments():
    return run([
        "kubectl", "scale",
        "deployment/payments",
        "--replicas=20",
        "-n", NAMESPACE
    ])


def misconfigure_service():
    run(["kubectl", "expose", "deployment", "gateway", "--port=80", "-n", NAMESPACE])
    return run([
        "kubectl", "patch", "service", "gateway",
        "-p", '{"spec":{"selector":{"app":"wrong"}}}',
        "-n", NAMESPACE
    ])


def revert():
    delete_all()
    return initialize_cluster()

def get_pod_status():
    out = run(["kubectl", "get", "pods", "-n", "ai-ops"])

    pods = []
    lines = out.splitlines()[1:]

    for l in lines:
        parts = l.split()
        if len(parts) < 4:
            continue

        pods.append({
            "name": parts[0],
            "status": parts[2],
            "restarts": parts[3]
        })

    return pods