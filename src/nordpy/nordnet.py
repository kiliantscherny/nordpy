# Based on code from https://github.com/Hundter/MitID-BrowserClient
# Copyright (c) 2024 Hundter - MIT License


# Script for https://www.nordnet.dk/logind
import requests, json, base64, sys, string, secrets, uuid, os, csv
from urllib.parse import urlparse, parse_qs
from bs4 import BeautifulSoup
sys.path.append("..")
sys.path.append(".")
from BrowserClient.Helpers import get_authentication_code, process_args, get_default_args
from datetime import datetime

SESSION_FILE = os.path.join(os.path.dirname(__file__), '.nordnet_session.json')
EXPORT_DIR = os.path.join(os.path.dirname(__file__), 'exports')

def save_session(session):
    """Save session cookies and headers to file"""
    session_data = {
        'cookies': session.cookies.get_dict(),
        'headers': dict(session.headers),
        'saved_at': datetime.now().isoformat()
    }
    with open(SESSION_FILE, 'w') as f:
        json.dump(session_data, f)
    print(f"Session saved to {SESSION_FILE}")

def load_session(session):
    """Load session cookies and headers from file"""
    if not os.path.exists(SESSION_FILE):
        return False

    try:
        with open(SESSION_FILE, 'r') as f:
            session_data = json.load(f)

        for name, value in session_data['cookies'].items():
            session.cookies.set(name, value)
        for name, value in session_data['headers'].items():
            session.headers[name] = value

        print(f"Loaded saved session from {session_data.get('saved_at', 'unknown time')}")
        return True
    except Exception as e:
        print(f"Failed to load session: {e}")
        return False

def test_session(session):
    """Test if the current session is still valid"""
    try:
        response = session.get('https://www.nordnet.dk/api/2/accounts')
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                return True
        return False
    except Exception:
        return False

def do_full_login(session, method, user_id, password):
    """Perform full MitID login flow"""
    nem_login_state = uuid.uuid4()
    digits = string.digits
    form_digits = ''.join(secrets.choice(digits) for i in range(29))

    login_url = f"https://id.signicat.com/oidc/authorize?client_id=prod.nordnet.dk.8x&response_type=code&redirect_uri=https://www.nordnet.dk/login&scope=openid signicat.national_id&acr_values=urn:signicat:oidc:method:mitid-cpr&state=NEXT_OIDC_STATE_{nem_login_state}"

    request = session.get(login_url)
    if request.status_code != 200:
        raise Exception(f"Failed session setup: {request.status_code}")

    soup = BeautifulSoup(request.text, 'lxml')
    next_url = soup.div['data-index-url']
    request = session.get(next_url)
    soup = BeautifulSoup(request.text, 'lxml')

    request = session.post(soup.div.next['data-base-url']+soup.div.next['data-init-auth-path'])
    if request.status_code != 200:
        raise Exception(f"Failed auth init: {request.status_code}")

    aux = json.loads(base64.b64decode(request.json()["aux"]))
    authorization_code = get_authentication_code(session, aux, method, user_id, password)
    print("MitID authentication successful")

    payload = f'''-----------------------------{form_digits}\r\nContent-Disposition: form-data; name="authCode"\r\n\r\n{authorization_code}\r\n-----------------------------{form_digits}--\r\n'''

    headers = {'Content-Type': f'multipart/form-data; boundary=---------------------------{form_digits}'}
    request = session.post(soup.div.next['data-base-url']+soup.div.next['data-auth-code-path'], data=payload, headers=headers)
    request = session.get(soup.div.next['data-base-url']+soup.div.next['data-finalize-auth-path'])

    if '/cpr' in request.url:
        print("CPR verification required")
        cpr_soup = BeautifulSoup(request.text, 'lxml')
        cpr_number = input("Please enter your CPR number (DDMMYYXXXX): ").strip()

        cpr_form = cpr_soup.find('main', {'id': 'cpr-form'})
        if not cpr_form:
            raise Exception("CPR form not found")

        cpr_base_url = cpr_form['data-base-url']
        verify_path = cpr_form['data-verify-path']
        finalize_path = cpr_form['data-finalize-cpr-path']

        verify_url = cpr_base_url + verify_path
        cpr_payload = {"cpr": cpr_number, "remember": "false"}
        request = session.post(verify_url, data=cpr_payload)

        if request.status_code != 200 or '"success":false' in request.text:
            raise Exception(f"CPR verification failed: {request.text}")

        print("CPR verified successfully")
        finalize_url = cpr_base_url + finalize_path
        request = session.get(finalize_url, allow_redirects=True)

    parsed_url = urlparse(request.url)
    code = parse_qs(parsed_url.query)['code'][0]

    payload = {
        "authenticationProvider": "SIGNICAT",
        "countryCode":"DK",
        "signicat": {
            "authorizationCode": code,
            "redirectUri":"https://www.nordnet.dk/login"
        }
    }

    session.headers['client-id'] = 'NEXT'
    request = session.post('https://www.nordnet.dk/nnxapi/authentication/v2/sessions', json=payload)
    if request.status_code != 200:
        raise Exception(f"Sessions failed: {request.status_code}")

    request = session.post('https://www.nordnet.dk/api/2/authentication/nnx-session/login', json={})
    if request.status_code != 200:
        raise Exception(f"Login failed: {request.status_code}")

    session.headers['ntag'] = request.headers['ntag']
    print("Successfully logged in to Nordnet!")
    save_session(session)

def export_to_csv(filename, headers, rows):
    """Export data to CSV file"""
    os.makedirs(EXPORT_DIR, exist_ok=True)
    filepath = os.path.join(EXPORT_DIR, filename)
    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"  Exported to {filepath}")

# Main script
argparser = get_default_args()
argparser.add_argument('--force-login', action='store_true', help='Force new login even if session exists')
argparser.add_argument('--export', action='store_true', help='Export data to CSV files')
args = argparser.parse_args()

method, user_id, password, proxy = process_args(args)
session = requests.Session()
if proxy:
    session.proxies.update({"http": f"socks5://{proxy}", "https": f"socks5://{proxy}"})

# Try to use existing session first
session_valid = False
if not args.force_login and load_session(session):
    print("Testing saved session...")
    if test_session(session):
        print("Saved session is still valid!")
        session_valid = True
    else:
        print("Saved session expired, need to login again")

if not session_valid:
    do_full_login(session, method, user_id, password)

# Get accounts
print("\n=== Your Nordnet Accounts ===")
accounts = session.get('https://www.nordnet.dk/api/2/accounts')
accounts_data = accounts.json()

for account in accounts_data:
    print(f"  Account {account['accid']}: {account.get('alias', account['type'])} (#{account['accno']})")

# Get account info/balances
print("\n=== Account Balances ===")
balance_rows = []
for account in accounts_data:
    accid = account['accid']
    info = session.get(f'https://www.nordnet.dk/api/2/accounts/{accid}/info')
    if info.status_code == 200:
        info_data = info.json()
        if isinstance(info_data, list) and len(info_data) > 0:
            info_data = info_data[0]
        if isinstance(info_data, dict):
            balance = info_data.get('account_sum', {}).get('value', 'N/A')
            currency = info_data.get('account_sum', {}).get('currency', '')
            print(f"  {account.get('alias', account['type'])}: {balance} {currency}")
            balance_rows.append([account['accno'], account.get('alias', account['type']), balance, currency, datetime.now().isoformat()])

if args.export and balance_rows:
    export_to_csv('balances.csv', ['Account Number', 'Account Name', 'Balance', 'Currency', 'Timestamp'], balance_rows)

# Get positions/holdings for each account
print("\n=== Holdings ===")
holdings_rows = []
for account in accounts_data:
    accid = account['accid']
    positions = session.get(f'https://www.nordnet.dk/api/2/accounts/{accid}/positions')
    if positions.status_code == 200:
        positions_data = positions.json()
        if positions_data:
            print(f"\n-- {account.get('alias', account['type'])} --")
            for pos in positions_data:
                instrument = pos.get('instrument', {})
                name = instrument.get('name', 'Unknown')
                isin = instrument.get('isin', '')
                symbol = instrument.get('symbol', '')
                qty = pos.get('qty', 0)
                acq_price = pos.get('acq_price', {}).get('value', 0)
                acq_price_curr = pos.get('acq_price', {}).get('currency', '')
                market_value = pos.get('market_value', {}).get('value', 0)
                market_curr = pos.get('market_value', {}).get('currency', '')
                pct_return = pos.get('morning_star_fact_sheet_url', '')  # placeholder

                print(f"  {name}: {qty} units @ {market_value} {market_curr}")
                holdings_rows.append([
                    account.get('alias', account['type']),
                    account['accno'],
                    name,
                    symbol,
                    isin,
                    qty,
                    acq_price,
                    acq_price_curr,
                    market_value,
                    market_curr,
                    datetime.now().isoformat()
                ])

if args.export and holdings_rows:
    export_to_csv('holdings.csv', [
        'Account', 'Account Number', 'Instrument', 'Symbol', 'ISIN',
        'Quantity', 'Acquisition Price', 'Acq Currency', 'Market Value', 'Currency', 'Timestamp'
    ], holdings_rows)

# Get trades/orders
print("\n=== Recent Trades ===")
trades_rows = []
for account in accounts_data:
    accid = account['accid']
    has_data = False

    # Try trades endpoint (executed trades)
    trades = session.get(f'https://www.nordnet.dk/api/2/accounts/{accid}/trades')
    if trades.status_code == 200:
        trades_data = trades.json()
        if trades_data:
            has_data = True
            print(f"\n-- {account.get('alias', account['type'])} (trades) --")
            for trade in trades_data[:10]:
                trade_date = trade.get('trade_time', trade.get('traded', 'N/A'))
                side = trade.get('side', 'N/A')
                instrument = trade.get('instrument', {}).get('name', 'Unknown')
                qty = trade.get('volume', trade.get('qty', 0))
                price = trade.get('price', {}).get('value', 0)
                currency = trade.get('price', {}).get('currency', '')
                print(f"  {trade_date} | {side:4} | {qty} x {instrument} @ {price} {currency}")
                trades_rows.append([
                    account.get('alias', account['type']),
                    trade_date,
                    side,
                    instrument,
                    qty,
                    price,
                    currency
                ])

    # Try orders endpoint (pending/historical orders)
    orders = session.get(f'https://www.nordnet.dk/api/2/accounts/{accid}/orders')
    if orders.status_code == 200:
        orders_data = orders.json()
        if orders_data:
            has_data = True
            print(f"\n-- {account.get('alias', account['type'])} (orders) --")
            for order in orders_data[:10]:
                order_date = order.get('order_date', order.get('valid_until', 'N/A'))
                side = order.get('side', 'N/A')
                instrument = order.get('instrument', {}).get('name', 'Unknown')
                qty = order.get('volume', 0)
                price = order.get('price', {}).get('value', 0)
                currency = order.get('price', {}).get('currency', '')
                state = order.get('order_state', 'N/A')
                print(f"  {order_date} | {side:4} | {qty} x {instrument} @ {price} {currency} [{state}]")

    if not has_data:
        print(f"\n-- {account.get('alias', account['type'])} --")
        print("  No recent trades or orders")

if args.export and trades_rows:
    export_to_csv('trades.csv', ['Account', 'Date', 'Side', 'Instrument', 'Quantity', 'Price', 'Currency'], trades_rows)

# Get bearer token for newer APIs
token_response = session.post('https://www.nordnet.dk/nnxapi/authorization/v1/tokens', json={})
bearer_token = None
if token_response.status_code in [200, 201]:
    bearer_token = token_response.json().get('jwt')

# Get historical transactions using newer API
print("\n=== Transaction History ===")
transaction_rows = []
if bearer_token:
    # Build account IDs string
    accids = ','.join([str(account['accid']) for account in accounts_data])

    # Set up headers for the newer API
    tx_headers = {
        'Authorization': f'Bearer {bearer_token}',
        'x-locale': 'da-DK',
        'client-id': 'NEXT'
    }

    # Get ALL transactions from account opening (use early date)
    from_date = '2010-01-01'
    to_date = datetime.now().strftime('%Y-%m-%d')

    # First get total count
    summary_url = f'https://api.prod.nntech.io/transaction/transaction-and-notes/v1/transaction-summary?fromDate={from_date}&toDate={to_date}&accids={accids}&includeCancellations=false'
    summary_response = session.get(summary_url, headers=tx_headers)
    total_transactions = 0
    if summary_response.status_code == 200:
        summary_data = summary_response.json()
        total_transactions = summary_data.get('numberOfTransactions', 0)
        print(f"Total transactions available: {total_transactions}")

    # Fetch transactions in batches (max 800 per request)
    all_transactions = []
    offset = 0
    limit = 800

    while True:
        tx_url = f'https://api.prod.nntech.io/transaction/transaction-and-notes/v1/transactions/page?fromDate={from_date}&toDate={to_date}&accids={accids}&offset={offset}&limit={limit}&sort=ACCOUNTING_DATE&sortOrder=DESC&includeCancellations=false'
        tx_response = session.get(tx_url, headers=tx_headers)

        if tx_response.status_code == 200:
            tx_data = tx_response.json()
            if isinstance(tx_data, list):
                batch = tx_data
            else:
                batch = tx_data.get('transactions', [])

            if not batch:
                break

            all_transactions.extend(batch)
            print(f"  Fetched {len(all_transactions)} transactions...")

            if len(batch) < limit:
                break
            offset += limit
        else:
            print(f"  Failed at offset {offset}: {tx_response.status_code}")
            break

    print(f"\nTotal fetched: {len(all_transactions)} transactions\n")

    # Debug: dump first transaction to see all available fields
    if all_transactions:
        print("=== RAW TRANSACTION STRUCTURE ===")
        import pprint
        pprint.pprint(all_transactions[0])
        print("=================================\n")

    # Show recent 20 on screen
    for tx in all_transactions[:20]:
        tx_date = tx.get('accountingDate', 'N/A')
        tx_type = tx.get('transactionTypeName', tx.get('transactionType', 'N/A'))

        amount_data = tx.get('amount', {})
        if isinstance(amount_data, dict):
            tx_amount = amount_data.get('value', 0)
            tx_currency = amount_data.get('currency', tx.get('currency', ''))
        else:
            tx_amount = amount_data
            tx_currency = tx.get('currency', '')

        tx_instrument = tx.get('instrumentName', tx.get('instrument', '')) or ''
        print(f"  {tx_date} | {tx_type:20} | {tx_amount:>12} {tx_currency} | {tx_instrument[:30]}")

    # Build full export with all columns
    for tx in all_transactions:
        # Match account by accountNumber
        acc_number = tx.get('accountNumber', '')
        acc_name = next((a.get('alias', a['type']) for a in accounts_data if a['accno'] == acc_number), 'Unknown')

        # Extract nested values safely
        def get_nested(d, default=''):
            if isinstance(d, dict):
                return d.get('value', default)
            return d if d else default

        def get_currency(d, default=''):
            if isinstance(d, dict):
                return d.get('currencyCode', default)
            return default

        # Get noteInfo fields
        note_info = tx.get('noteInfo', {})

        transaction_rows.append([
            acc_name,
            acc_number,
            tx.get('accountingDate', ''),
            tx.get('settlementDate', ''),
            tx.get('businessDate', ''),
            tx.get('transactionTypeName', ''),
            tx.get('transactionTypeCode', ''),
            tx.get('instrumentName', '') or '',
            tx.get('instrumentShortName', ''),
            tx.get('isinCode', ''),
            tx.get('quantity', ''),
            get_nested(tx.get('price', {})),
            get_currency(tx.get('price', {})),
            get_nested(tx.get('amount', {})),
            get_currency(tx.get('amount', {})),
            get_nested(tx.get('balance', {})),
            tx.get('fxPrice', ''),
            tx.get('currencyFrom', ''),
            tx.get('currencyTo', ''),
            get_nested(tx.get('acquisitionCost', {})),
            get_currency(tx.get('acquisitionCost', {})),
            get_nested(note_info.get('commission', {})),
            get_nested(note_info.get('charge', {})),
            get_nested(note_info.get('foreignCharge', {})),
            get_nested(note_info.get('handlingFee', {})),
            get_nested(note_info.get('stampTax', {})),
            get_nested(tx.get('totalCharges', {})),
            tx.get('contractNoteNumber', ''),
            tx.get('transactionId', ''),
            tx.get('backofficeTransactionId', ''),
        ])
else:
    print("  Could not obtain bearer token for transaction API")

if args.export and transaction_rows:
    export_to_csv('transactions.csv', [
        'Account', 'Account Number', 'Accounting Date', 'Settlement Date', 'Business Date',
        'Type', 'Type Code', 'Instrument', 'Short Name', 'ISIN',
        'Quantity', 'Price', 'Price Currency', 'Amount', 'Amount Currency',
        'Balance After', 'FX Rate', 'Currency From', 'Currency To',
        'Acquisition Cost', 'Acq Cost Currency', 'Commission', 'Charge',
        'Foreign Charge', 'Handling Fee', 'Stamp Tax', 'Total Charges',
        'Contract Note', 'Transaction ID', 'Backoffice ID'
    ], transaction_rows)

# Summary
print("\n=== Summary ===")
total_holdings = len(holdings_rows)
total_accounts = len(accounts_data)
print(f"  {total_accounts} accounts with {total_holdings} positions")

if args.export:
    print(f"\n  CSV files exported to: {EXPORT_DIR}/")
