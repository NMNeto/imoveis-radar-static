#!/usr/bin/env python3
"""Envia o e-mail de alerta quando a atualização falha no GitHub Actions.

Configurado por variáveis de ambiente (todas vindas de *secrets*):

* ``SMTP_HOST``, ``SMTP_PORT`` (padrão 587), ``SMTP_SECURITY``
  (``starttls`` | ``ssl`` | ``none``);
* ``SMTP_USER``, ``SMTP_PASS``;
* ``ALERT_EMAIL_FROM`` (padrão: ``SMTP_USER``), ``ALERT_EMAIL_TO``
  (vários endereços separados por vírgula);
* ``ALERT_SUBJECT_PREFIX`` (padrão ``[Imovanta]``).

Sem ``SMTP_HOST`` ou ``ALERT_EMAIL_TO`` o script apenas avisa no log e sai com
0: o job já está falhando por causa do problema real.

Uso:
    python scripts/enviar_alerta_email.py
    python scripts/enviar_alerta_email.py --summary public/data/ultima_atualizacao.json
"""
from __future__ import annotations

import argparse
import json
import os
import smtplib
import sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from checar_fontes import SUMMARY_PATH, check_summary, describe  # noqa: E402


def run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return os.environ.get("ALERT_RUN_URL", "")


def build_message(
    summary: dict,
    problemas: list,
    *,
    link: str = "",
    prefix: str = "[Imovanta]",
    max_stale_days: int = 3,
) -> tuple[str, str]:
    fontes = ", ".join(problema.fonte for problema in problemas) or "sem detalhe"
    assunto = f"{prefix} Falha na atualização ({fontes})"

    linhas = [
        "A atualização automática do Imovanta encontrou problema(s):",
        "",
        describe(summary, problemas, max_stale_days),
        "",
    ]
    atualizacao = summary.get("data_atualizacao") or "(desconhecida)"
    linhas.append(f"Última publicação: {atualizacao}")
    if link:
        linhas += ["", f"Log completo: {link}"]
    linhas += [
        "",
        "Os dados anteriores continuam publicados; nada foi apagado.",
        "",
        "— Imovanta (alerta automático)",
    ]
    return assunto, "\n".join(linhas)


def send(
    *,
    host: str,
    port: int,
    security: str,
    user: str | None,
    secret: str | None,
    sender: str,
    recipients: list[str],
    subject: str,
    body: str,
    timeout: int = 30,
) -> None:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message["Date"] = formatdate(localtime=True)
    message["Message-ID"] = make_msgid()
    message.set_content(body)

    if security == "ssl":
        client = smtplib.SMTP_SSL(host, port, timeout=timeout)
    else:
        client = smtplib.SMTP(host, port, timeout=timeout)
    with client:
        if security == "starttls":
            client.starttls()
        if user and secret:
            client.login(user, secret)
        client.send_message(message)


def build_test_message(prefix: str = "[Imovanta]") -> tuple[str, str]:
    """Mensagem fixa para validar os secrets, sem depender do resumo."""
    assunto = f"{prefix} Teste de alerta por e-mail"
    corpo = "\n".join(
        [
            "Este é um teste do alerta automático do Imovanta.",
            "",
            "Se você recebeu esta mensagem, os secrets SMTP_* estão corretos e o",
            "pipeline consegue avisar quando uma fonte ficar sem dados.",
            "",
            "Nenhum dado foi alterado.",
            "",
            "— Imovanta (alerta automático)",
        ]
    )
    return assunto, corpo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument(
        "--test",
        action="store_true",
        help="envia uma mensagem de teste (valida os secrets)",
    )
    parser.add_argument("--max-age-hours", type=float, default=0)
    parser.add_argument("--max-stale-days", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="imprime sem enviar")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    host = os.environ.get("SMTP_HOST", "").strip()
    recipients = [
        endereco.strip()
        for endereco in os.environ.get("ALERT_EMAIL_TO", "").split(",")
        if endereco.strip()
    ]
    if not host or not recipients:
        print(
            "SMTP_HOST/ALERT_EMAIL_TO não configurados."
            + ("" if args.test else " Alerta não enviado."),
            file=sys.stderr,
        )
        return 2 if args.test else 0

    prefixo = os.environ.get("ALERT_SUBJECT_PREFIX", "[Imovanta]")
    if args.test:
        assunto, corpo = build_test_message(prefixo)
    else:
        try:
            summary = json.loads(args.summary.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            summary = {}

        problemas = check_summary(
            summary,
            max_age_hours=args.max_age_hours,
            max_stale_days=args.max_stale_days,
        )
        assunto, corpo = build_message(
            summary,
            problemas,
            link=run_url(),
            prefix=prefixo,
            max_stale_days=args.max_stale_days,
        )

    if args.dry_run:
        print(f"Assunto: {assunto}\n\n{corpo}")
        return 0

    sender = os.environ.get("ALERT_EMAIL_FROM") or os.environ.get("SMTP_USER", "")
    try:
        send(
            host=host,
            port=int(os.environ.get("SMTP_PORT", "587")),
            security=os.environ.get("SMTP_SECURITY", "starttls").lower(),
            user=os.environ.get("SMTP_USER") or None,
            secret=os.environ.get("SMTP_PASS") or None,
            sender=sender,
            recipients=recipients,
            subject=assunto,
            body=corpo,
        )
    except Exception as exc:  # noqa: BLE001 - alerta nunca esconde a falha real
        print(f"Falha ao enviar o e-mail de alerta: {exc}", file=sys.stderr)
        return 1 if args.test else 0
    print(f"Alerta enviado para {', '.join(recipients)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
