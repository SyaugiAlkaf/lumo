#![cfg(test)]
extern crate std;

use ed25519_dalek::{Keypair, Signer};
use rand::thread_rng;
use soroban_sdk::auth::{Context, ContractContext};
use soroban_sdk::testutils::{Address as _, AuthorizedFunction, BytesN as _};
use soroban_sdk::{token, vec, Address, BytesN, Env, IntoVal, Symbol, TryIntoVal, Val, Vec};

use crate::{Ed25519Signature, Error, PolicyAccount, PolicyAccountClient};

const CAP: i128 = 1_000;
const AMOUNT: i128 = 500;

fn keypair() -> Keypair {
    Keypair::generate(&mut thread_rng())
}

fn pk(e: &Env, k: &Keypair) -> BytesN<32> {
    k.public.to_bytes().into_val(e)
}

fn sign(e: &Env, k: &Keypair, payload: &BytesN<32>) -> Val {
    Ed25519Signature {
        public_key: pk(e, k),
        signature: k.sign(payload.to_array().as_slice()).to_bytes().into_val(e),
    }
    .into_val(e)
}

struct Fixture {
    env: Env,
    owner: Keypair,
    account: Address,
    escrow: Address,
    supplier: Address,
}

fn setup() -> Fixture {
    let env = Env::default();
    env.mock_all_auths();
    let owner = keypair();
    let account = env.register(PolicyAccount, (pk(&env, &owner), CAP));
    let supplier = Address::generate(&env);
    PolicyAccountClient::new(&env, &account).add_supplier(&supplier);
    let escrow = Address::generate(&env);
    Fixture {
        env,
        owner,
        account,
        escrow,
        supplier,
    }
}

fn create_intent_ctx(f: &Fixture, supplier: &Address, amount: i128) -> Context {
    let sme = Address::generate(&f.env);
    let token = Address::generate(&f.env);
    let hash = BytesN::from_array(&f.env, &[0u8; 32]);
    Context::Contract(ContractContext {
        contract: f.escrow.clone(),
        fn_name: Symbol::new(&f.env, "create_intent"),
        args: (sme, supplier.clone(), token, amount, hash, 0u64).into_val(&f.env),
    })
}

fn check(f: &Fixture, ctxs: Vec<Context>) -> Result<(), Error> {
    let payload = BytesN::random(&f.env);
    f.env
        .try_invoke_contract_check_auth::<Error>(
            &f.account,
            &payload,
            sign(&f.env, &f.owner, &payload),
            &ctxs,
        )
        .map_err(|e| e.unwrap())
}

#[test]
fn t4_in_policy_passes() {
    let f = setup();
    let ctx = create_intent_ctx(&f, &f.supplier, AMOUNT);
    check(&f, vec![&f.env, ctx]).unwrap();
}

#[test]
fn t4_over_cap_denied() {
    let f = setup();
    let ctx = create_intent_ctx(&f, &f.supplier, CAP + 1);
    assert_eq!(check(&f, vec![&f.env, ctx]), Err(Error::OverCap));
}

#[test]
fn t4_unapproved_supplier_denied() {
    let f = setup();
    let stranger = Address::generate(&f.env);
    let ctx = create_intent_ctx(&f, &stranger, AMOUNT);
    assert_eq!(check(&f, vec![&f.env, ctx]), Err(Error::SupplierNotApproved));
}

#[test]
fn t4_unknown_fn_denied() {
    let f = setup();
    let ctx = Context::Contract(ContractContext {
        contract: f.escrow.clone(),
        fn_name: Symbol::new(&f.env, "burn"),
        args: (Address::generate(&f.env), AMOUNT).into_val(&f.env),
    });
    assert_eq!(check(&f, vec![&f.env, ctx]), Err(Error::FnNotAllowed));
}

#[test]
fn t4_bad_sig_rejected() {
    let f = setup();
    let attacker = keypair();
    let payload = BytesN::random(&f.env);
    let ctx = create_intent_ctx(&f, &f.supplier, AMOUNT);
    let res = f.env.try_invoke_contract_check_auth::<Error>(
        &f.account,
        &payload,
        sign(&f.env, &attacker, &payload),
        &vec![&f.env, ctx],
    );
    assert_eq!(res.err().unwrap().unwrap(), Error::BadSignature);
}

#[test]
fn t4_create_contract_denied() {
    let f = setup();
    let transfer = Context::Contract(ContractContext {
        contract: Address::generate(&f.env),
        fn_name: Symbol::new(&f.env, "transfer"),
        args: (Address::generate(&f.env), Address::generate(&f.env), CAP).into_val(&f.env),
    });
    let over = Context::Contract(ContractContext {
        contract: Address::generate(&f.env),
        fn_name: Symbol::new(&f.env, "transfer"),
        args: (Address::generate(&f.env), Address::generate(&f.env), CAP + 1).into_val(&f.env),
    });
    check(&f, vec![&f.env, transfer]).unwrap();
    assert_eq!(check(&f, vec![&f.env, over]), Err(Error::OverCap));
}

#[test]
fn t4_self_admin_allowed_others_denied() {
    let f = setup();
    let admin_ctx = Context::Contract(ContractContext {
        contract: f.account.clone(),
        fn_name: Symbol::new(&f.env, "set_cap"),
        args: (2_000i128,).into_val(&f.env),
    });
    let foreign_self = Context::Contract(ContractContext {
        contract: f.account.clone(),
        fn_name: Symbol::new(&f.env, "drain"),
        args: ().into_val(&f.env),
    });
    check(&f, vec![&f.env, admin_ctx]).unwrap();
    assert_eq!(check(&f, vec![&f.env, foreign_self]), Err(Error::FnNotAllowed));
}

// Freezes escrow::create_intent(sme, supplier, token, amount, request_hash,
// deadline) positional order: captures the authorized args from a real escrow
// invocation and asserts supplier@1 / amount@3 — the positions __check_auth
// reads. A reorder in the escrow ABI breaks this test, not money.
#[test]
fn guard_create_intent_arg_order() {
    let env = Env::default();
    env.mock_all_auths();

    let admin = Address::generate(&env);
    let escrow = env.register(lumo_escrow::LumoEscrow, (admin.clone(),));
    let escrow_client = lumo_escrow::LumoEscrowClient::new(&env, &escrow);
    escrow_client.add_oracle(&admin);

    let sac = env.register_stellar_asset_contract_v2(Address::generate(&env));
    let token_id = sac.address();
    let sme = Address::generate(&env);
    let supplier = Address::generate(&env);
    token::StellarAssetClient::new(&env, &token_id).mint(&sme, &AMOUNT);

    let hash = BytesN::from_array(&env, &[9u8; 32]);
    escrow_client.create_intent(&sme, &supplier, &token_id, &AMOUNT, &hash, &1_000u64);

    let auths = env.auths();
    let (_, inv) = auths.iter().find(|(a, _)| a == &sme).unwrap();
    let (contract, fn_name, args) = match inv.function.clone() {
        AuthorizedFunction::Contract(inner) => inner,
        _ => panic!("expected contract call"),
    };
    assert_eq!(fn_name, Symbol::new(&env, "create_intent"));
    let got_supplier: Address = args.get(1).unwrap().try_into_val(&env).unwrap();
    let got_amount: i128 = args.get(3).unwrap().try_into_val(&env).unwrap();
    assert_eq!(got_supplier, supplier);
    assert_eq!(got_amount, AMOUNT);

    let owner = keypair();
    let account = env.register(PolicyAccount, (pk(&env, &owner), CAP));
    PolicyAccountClient::new(&env, &account).add_supplier(&supplier);
    let ctx = Context::Contract(ContractContext { contract, fn_name, args });
    let payload = BytesN::random(&env);
    env.try_invoke_contract_check_auth::<Error>(
        &account,
        &payload,
        sign(&env, &owner, &payload),
        &vec![&env, ctx],
    )
    .unwrap();
}
