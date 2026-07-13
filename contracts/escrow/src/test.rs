#![cfg(test)]
use super::*;
use soroban_sdk::{
    testutils::{Address as _, Ledger, MockAuth, MockAuthInvoke},
    token, Address, BytesN, Env, IntoVal,
};

const AMOUNT: i128 = 1_000;
const MINT: i128 = 10_000;
const DEADLINE: u64 = 86_400;

struct Fixture {
    env: Env,
    client: AmanahEscrowClient<'static>,
    contract_id: Address,
    token_id: Address,
    token: token::Client<'static>,
    oracle: Address,
    sme: Address,
    supplier: Address,
}

fn setup() -> Fixture {
    let env = Env::default();
    env.mock_all_auths();

    let token_admin = Address::generate(&env);
    let sac = env.register_stellar_asset_contract_v2(token_admin.clone());
    let token_id = sac.address();
    let token = token::Client::new(&env, &token_id);
    let token_minter = token::StellarAssetClient::new(&env, &token_id);

    let admin = Address::generate(&env);
    let oracle = Address::generate(&env);
    let sme = Address::generate(&env);
    let supplier = Address::generate(&env);
    token_minter.mint(&sme, &MINT);

    let contract_id = env.register(AmanahEscrow, (admin,));
    let client = AmanahEscrowClient::new(&env, &contract_id);
    client.add_oracle(&oracle);

    Fixture {
        env,
        client,
        contract_id,
        token_id,
        token,
        oracle,
        sme,
        supplier,
    }
}

fn hash(env: &Env) -> BytesN<32> {
    BytesN::from_array(env, &[7u8; 32])
}

fn fund(f: &Fixture) -> u64 {
    f.client
        .create_intent(&f.sme, &f.supplier, &f.token_id, &AMOUNT, &hash(&f.env), &DEADLINE)
}

#[test]
fn t3_create_funds_escrow() {
    let f = setup();
    let id = fund(&f);

    assert_eq!(id, 1);
    assert_eq!(f.token.balance(&f.sme), MINT - AMOUNT);
    assert_eq!(f.token.balance(&f.contract_id), AMOUNT);
    let intent = f.client.get_intent(&id).unwrap();
    assert_eq!(intent.status, Status::Funded);
    assert_eq!(intent.supplier, f.supplier);
    assert_eq!(intent.amount, AMOUNT);
    assert_eq!(intent.attestation, Attestation::None);
}

#[test]
fn t1_release_pays_bound_supplier_after_shipped() {
    let f = setup();
    let id = fund(&f);

    f.client.attest(&id, &f.oracle, &AttestKind::Shipped);
    f.client.release(&id);

    assert_eq!(f.token.balance(&f.supplier), AMOUNT);
    assert_eq!(f.token.balance(&f.contract_id), 0);
    assert_eq!(f.token.balance(&f.sme), MINT - AMOUNT);
    assert_eq!(f.client.get_intent(&id).unwrap().status, Status::Released);
}

#[test]
fn t2_release_without_attestation_reverts_and_moves_nothing() {
    let f = setup();
    let id = fund(&f);

    assert_eq!(f.client.try_release(&id), Err(Ok(Error::NoAttestation)));

    assert_eq!(f.token.balance(&f.supplier), 0);
    assert_eq!(f.token.balance(&f.contract_id), AMOUNT);
    assert_eq!(f.token.balance(&f.sme), MINT - AMOUNT);
    assert_eq!(f.client.get_intent(&id).unwrap().status, Status::Funded);
}

#[test]
fn t3_release_after_failed_reverts_intent_failed() {
    let f = setup();
    let id = fund(&f);

    f.client.attest(&id, &f.oracle, &AttestKind::Failed);
    assert_eq!(f.client.try_release(&id), Err(Ok(Error::IntentFailed)));

    assert_eq!(f.token.balance(&f.supplier), 0);
    assert_eq!(f.token.balance(&f.contract_id), AMOUNT);
}

#[test]
fn t3_refund_before_deadline_reverts_not_yet_expired() {
    let f = setup();
    let id = fund(&f);

    assert_eq!(f.client.try_refund(&id), Err(Ok(Error::NotYetExpired)));

    assert_eq!(f.token.balance(&f.sme), MINT - AMOUNT);
    assert_eq!(f.token.balance(&f.contract_id), AMOUNT);
}

#[test]
fn t3_release_pays_only_bound_supplier_not_caller() {
    let f = setup();
    let attacker = Address::generate(&f.env);
    let id = fund(&f);

    f.client.attest(&id, &f.oracle, &AttestKind::Shipped);
    f.client.release(&id);

    assert_eq!(f.token.balance(&attacker), 0);
    assert_eq!(f.token.balance(&f.supplier), AMOUNT);
}

#[test]
fn t3_double_finalize_reverts_already_finalized() {
    let f = setup();
    let id = fund(&f);

    f.client.attest(&id, &f.oracle, &AttestKind::Shipped);
    f.client.release(&id);

    assert_eq!(f.client.try_release(&id), Err(Ok(Error::AlreadyFinalized)));
    assert_eq!(f.client.try_refund(&id), Err(Ok(Error::AlreadyFinalized)));
    assert_eq!(f.token.balance(&f.supplier), AMOUNT);
}

#[test]
fn t3_shipped_attestation_beats_deadline() {
    let f = setup();
    let id = fund(&f);

    f.client.attest(&id, &f.oracle, &AttestKind::Shipped);
    f.env.ledger().set_timestamp(DEADLINE + 1);

    assert_eq!(f.client.try_refund(&id), Err(Ok(Error::IntentShipped)));
    f.client.release(&id);
    assert_eq!(f.token.balance(&f.supplier), AMOUNT);
    assert_eq!(f.token.balance(&f.sme), MINT - AMOUNT);
}

#[test]
fn refund_after_failed_returns_funds_to_sme() {
    let f = setup();
    let id = fund(&f);

    f.client.attest(&id, &f.oracle, &AttestKind::Failed);
    f.client.refund(&id);

    assert_eq!(f.token.balance(&f.sme), MINT);
    assert_eq!(f.token.balance(&f.contract_id), 0);
    assert_eq!(f.token.balance(&f.supplier), 0);
    assert_eq!(f.client.get_intent(&id).unwrap().status, Status::Refunded);
}

#[test]
fn refund_after_deadline_without_attestation_returns_funds_to_sme() {
    let f = setup();
    let id = fund(&f);

    f.env.ledger().set_timestamp(DEADLINE);
    f.client.refund(&id);

    assert_eq!(f.token.balance(&f.sme), MINT);
    assert_eq!(f.token.balance(&f.supplier), 0);
}

#[test]
fn t5_attest_from_unregistered_oracle_is_rejected() {
    let f = setup();
    let stranger = Address::generate(&f.env);
    let id = fund(&f);

    assert_eq!(
        f.client.try_attest(&id, &stranger, &AttestKind::Shipped),
        Err(Ok(Error::NotOracle))
    );
    assert_eq!(f.client.get_intent(&id).unwrap().attestation, Attestation::None);
}

#[test]
fn t5_removed_oracle_is_rejected() {
    let f = setup();
    f.client.remove_oracle(&f.oracle);
    let id = fund(&f);

    assert_eq!(
        f.client.try_attest(&id, &f.oracle, &AttestKind::Shipped),
        Err(Ok(Error::NotOracle))
    );
    assert_eq!(f.client.get_intent(&id).unwrap().attestation, Attestation::None);
}

#[test]
fn t5_non_admin_cannot_add_oracle() {
    let env = Env::default();
    let admin = Address::generate(&env);
    let contract_id = env.register(AmanahEscrow, (admin,));
    let client = AmanahEscrowClient::new(&env, &contract_id);
    let stranger = Address::generate(&env);
    let oracle = Address::generate(&env);

    let res = client
        .mock_auths(&[MockAuth {
            address: &stranger,
            invoke: &MockAuthInvoke {
                contract: &contract_id,
                fn_name: "add_oracle",
                args: (oracle.clone(),).into_val(&env),
                sub_invokes: &[],
            },
        }])
        .try_add_oracle(&oracle);

    assert!(res.is_err());
    assert!(!client.is_oracle(&oracle));
}

#[test]
fn attest_is_first_write_wins() {
    let f = setup();
    let id = fund(&f);

    f.client.attest(&id, &f.oracle, &AttestKind::Shipped);
    assert_eq!(
        f.client.try_attest(&id, &f.oracle, &AttestKind::Failed),
        Err(Ok(Error::AlreadyAttested))
    );

    f.client.release(&id);
    assert_eq!(f.token.balance(&f.supplier), AMOUNT);
}
