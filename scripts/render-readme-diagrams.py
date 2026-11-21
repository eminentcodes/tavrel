"""Generate GitHub-renderable SVG documentation using Tavrel's design colors."""
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs'
OUT.mkdir(exist_ok=True)
INK, MUTED, PURPLE, LINE = '#171818', '#676965', '#5c456d', '#dedfda'

def text(x, y, label, size=23, color=INK, weight=400, anchor='start'):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{escape(label)}</text>'

def box(x, y, w, h, title, lines, number=None, purple=False):
    parts = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="24" fill="{"#eee8f2" if purple else "#fafaf8"}" stroke="{LINE}"/>']
    if number:
        parts += [text(x+25,y+38,number,17,PURPLE,600)]
    parts += [text(x+25,y+78 if number else y+48,title,28,INK,500)]
    base = y+114 if number else y+84
    parts += [text(x+25,base+i*31,line,21,MUTED) for i,line in enumerate(lines)]
    return ''.join(parts)

def arrow(path, label=None, x=0, y=0):
    content=f'<path d="{path}" fill="none" stroke="{PURPLE}" stroke-width="2.5" marker-end="url(#arrow)"/>'
    if label: content += text(x,y,label,18,MUTED)
    return content

def svg(title, description, height, body):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 {height}" role="img" aria-labelledby="title desc">
<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>
<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="4" orient="auto"><path d="M0 0L8 4L0 8" fill="none" stroke="{PURPLE}" stroke-width="1.4"/></marker></defs>
<rect width="1400" height="{height}" rx="30" fill="#f0f0ee"/>
<g font-family="Arial, Helvetica, sans-serif">
{text(55,76,title,34,INK,500)}{body}
</g></svg>\n'''

workflow = ''.join([
    box(55,125,395,190,'Set the rules',['Sender, recipients, allowance,','payment cap and approval threshold.'],'01'),
    box(500,125,395,190,'Give the agent a task',['Exact payment details are checked.','Eligible requests reserve allowance.'],'02'),
    box(945,125,395,190,'Review when required',['Larger requests wait for approval.','Blocked requests cannot be signed.'],'03',True),
    arrow('M450 220H486'), arrow('M895 220H931'), arrow('M1142 315V376'),
    box(945,390,395,190,'Sign and submit',['Your wallet or an authorized agent','wallet signs; Tavrel saves and sends.'],'04'),
    box(500,390,395,190,'Check finality',['Match the transaction and transfer','events in finalized Volta blocks.'],'05'),
    box(55,390,395,190,'Record the outcome',['Confirmed principal is counted once.','Receipts preserve payment evidence.'],'06',True),
    arrow('M945 485H909'), arrow('M500 485H464'),
    text(55,639,'Retries keep the same payment identity. Uncertain outcomes retain their allowance reservation.',20,MUTED)
])
(OUT/'payment-workflow.svg').write_text(svg('How Tavrel payments work','Six steps from spending rules to a finalized transaction receipt, including required approval and wallet signing.',680,workflow),encoding='utf-8')

architecture = ''.join([
    box(55,126,390,170,'Browser app + wallet',['Browse and manage your account.','Sign login messages and transfers.']),
    box(505,126,390,170,'Agent task API',['Task tokens prepare and inspect','payments; they cannot approve.']),
    box(955,126,390,170,'zkVerify Volta',['Live balance, metadata, fees,','submission and finalized events.']),
    arrow('M250 296V388','Signed wallet session',75,345),
    arrow('M700 296V388','Owner-scoped task token',543,345),
    arrow('M1150 296V388','Native RPC',1180,345),
    box(55,405,1290,215,'Tavrel gateway',['Wallet authentication and account routing  •  Deterministic payment tasks  •  Recipient and allowance checks',
        'Request-bound approval  •  Signature validation  •  Durable submission and finalized receipt reconciliation'],purple=True),
    arrow('M250 620V692'),arrow('M700 620V692'),arrow('M1150 620V692'),
    box(55,710,390,170,'Per-wallet SQLite ledgers',['Agents, rules, approvals, payment','holds, transactions and receipts.']),
    box(505,710,390,170,'Encrypted agent wallets',['Separate keys with explicit signing','permission, limits and expiry.']),
    box(955,710,390,170,'Optional local policy proof',['FFLONK recipient/allowance proof.','Separate from transfer finality.']),
    text(55,937,'Browser-wallet keys stay in the extension. Hosted users have separate payment ledgers.',20,MUTED)
])
(OUT/'architecture.svg').write_text(svg('Tavrel architecture','Browser wallet sessions and scoped agent tokens route through Tavrel to isolated ledgers and the zkVerify Volta network. Automatic agent wallets and policy proving are separate services.',980,architecture),encoding='utf-8')
print('Workflow and architecture SVGs generated.')
