#![no_std]
use soroban_sdk::{contract, contracterror, contractimpl, contracttype, Address, BytesN, Env};

#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
#[repr(u32)]
pub enum Error {
    IntentNotFound = 1,
    NotOracle = 2,
    AlreadyAttested = 3,
    NoAttestation = 4,
    IntentFailed = 5,
    IntentShipped = 6,
    NotYetExpired = 7,
    AlreadyFinalized = 8,
}

#[contracttype]
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum Status {
    Funded,
    Released,
    Refunded,
}

#[contracttype]
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum AttestKind {
    Shipped,
    Failed,
}

#[contracttype]
#[derive(Copy, Clone, Debug, Eq, PartialEq)]
pub enum Attestation {
    None,
    Shipped,
    Failed,
}

#[contracttype]
#[derive(Clone)]
pub struct Intent {
    pub sme: Address,
    pub supplier: Address,
    pub token: Address,
    pub amount: i128,
    pub request_hash: BytesN<32>,
    pub deadline: u64,
    pub status: Status,
    pub attestation: Attestation,
}

#[contract]
pub struct AmanahEscrow;

#[contractimpl]
impl AmanahEscrow {
    pub fn __constructor(_env: Env, _admin: Address) {
        unimplemented!()
    }

    pub fn add_oracle(_env: Env, _oracle: Address) {
        unimplemented!()
    }

    pub fn remove_oracle(_env: Env, _oracle: Address) {
        unimplemented!()
    }

    pub fn is_oracle(_env: Env, _oracle: Address) -> bool {
        unimplemented!()
    }

    pub fn create_intent(
        _env: Env,
        _sme: Address,
        _supplier: Address,
        _token: Address,
        _amount: i128,
        _request_hash: BytesN<32>,
        _deadline: u64,
    ) -> u64 {
        unimplemented!()
    }

    pub fn attest(_env: Env, _intent_id: u64, _oracle: Address, _kind: AttestKind) -> Result<(), Error> {
        unimplemented!()
    }

    pub fn release(_env: Env, _intent_id: u64) -> Result<(), Error> {
        unimplemented!()
    }

    pub fn refund(_env: Env, _intent_id: u64) -> Result<(), Error> {
        unimplemented!()
    }

    pub fn get_intent(_env: Env, _intent_id: u64) -> Option<Intent> {
        unimplemented!()
    }
}

mod test;
