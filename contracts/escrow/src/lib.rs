#![no_std]
use soroban_sdk::{
    contract, contracterror, contractevent, contractimpl, contracttype, token, Address, BytesN, Env,
};

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

#[contractevent(topics = ["intent"])]
pub struct Created {
    #[topic]
    pub id: u64,
    pub sme: Address,
    pub supplier: Address,
    pub amount: i128,
}

#[contractevent(topics = ["intent"])]
pub struct Attested {
    #[topic]
    pub id: u64,
    pub kind: AttestKind,
}

#[contractevent(topics = ["intent"])]
pub struct Released {
    #[topic]
    pub id: u64,
    pub supplier: Address,
    pub amount: i128,
}

#[contractevent(topics = ["intent"])]
pub struct Refunded {
    #[topic]
    pub id: u64,
    pub sme: Address,
    pub amount: i128,
}

#[contracttype]
pub enum Key {
    Admin,
    Counter,
    Oracle(Address),
    Intent(u64),
}

const DAY_LEDGERS: u32 = 17280;
const BUMP_THRESHOLD: u32 = 30 * DAY_LEDGERS;
const BUMP_EXTEND: u32 = 90 * DAY_LEDGERS;

#[contract]
pub struct LumoEscrow;

#[contractimpl]
impl LumoEscrow {
    pub fn __constructor(env: Env, admin: Address) {
        env.storage().instance().set(&Key::Admin, &admin);
    }

    pub fn add_oracle(env: Env, oracle: Address) {
        Self::admin(&env).require_auth();
        env.storage().persistent().set(&Key::Oracle(oracle.clone()), &true);
        env.storage()
            .persistent()
            .extend_ttl(&Key::Oracle(oracle), BUMP_THRESHOLD, BUMP_EXTEND);
    }

    pub fn remove_oracle(env: Env, oracle: Address) {
        Self::admin(&env).require_auth();
        env.storage().persistent().remove(&Key::Oracle(oracle));
    }

    pub fn is_oracle(env: Env, oracle: Address) -> bool {
        Self::oracle_registered(&env, &oracle)
    }

    pub fn create_intent(
        env: Env,
        sme: Address,
        supplier: Address,
        token: Address,
        amount: i128,
        request_hash: BytesN<32>,
        deadline: u64,
    ) -> u64 {
        sme.require_auth();
        token::Client::new(&env, &token).transfer(&sme, &env.current_contract_address(), &amount);

        let id = Self::next_id(&env);
        let intent = Intent {
            sme,
            supplier,
            token,
            amount,
            request_hash,
            deadline,
            status: Status::Funded,
            attestation: Attestation::None,
        };
        env.storage().persistent().set(&Key::Intent(id), &intent);
        env.storage()
            .persistent()
            .extend_ttl(&Key::Intent(id), BUMP_THRESHOLD, BUMP_EXTEND);

        Created {
            id,
            sme: intent.sme.clone(),
            supplier: intent.supplier.clone(),
            amount,
        }
        .publish(&env);
        id
    }

    pub fn attest(env: Env, intent_id: u64, oracle: Address, kind: AttestKind) -> Result<(), Error> {
        oracle.require_auth();
        if !Self::oracle_registered(&env, &oracle) {
            return Err(Error::NotOracle);
        }

        let mut intent = Self::load(&env, intent_id)?;
        if intent.status != Status::Funded {
            return Err(Error::AlreadyFinalized);
        }
        if intent.attestation != Attestation::None {
            return Err(Error::AlreadyAttested);
        }

        intent.attestation = match kind {
            AttestKind::Shipped => Attestation::Shipped,
            AttestKind::Failed => Attestation::Failed,
        };
        env.storage().persistent().set(&Key::Intent(intent_id), &intent);
        Attested { id: intent_id, kind }.publish(&env);
        Ok(())
    }

    pub fn release(env: Env, intent_id: u64) -> Result<(), Error> {
        let mut intent = Self::load(&env, intent_id)?;
        if intent.status != Status::Funded {
            return Err(Error::AlreadyFinalized);
        }
        match intent.attestation {
            Attestation::Shipped => {}
            Attestation::Failed => return Err(Error::IntentFailed),
            Attestation::None => return Err(Error::NoAttestation),
        }

        token::Client::new(&env, &intent.token).transfer(
            &env.current_contract_address(),
            &intent.supplier,
            &intent.amount,
        );
        intent.status = Status::Released;
        env.storage().persistent().set(&Key::Intent(intent_id), &intent);
        Released {
            id: intent_id,
            supplier: intent.supplier.clone(),
            amount: intent.amount,
        }
        .publish(&env);
        Ok(())
    }

    pub fn refund(env: Env, intent_id: u64) -> Result<(), Error> {
        let mut intent = Self::load(&env, intent_id)?;
        if intent.status != Status::Funded {
            return Err(Error::AlreadyFinalized);
        }
        match intent.attestation {
            Attestation::Shipped => return Err(Error::IntentShipped),
            Attestation::Failed => {}
            Attestation::None => {
                if env.ledger().timestamp() < intent.deadline {
                    return Err(Error::NotYetExpired);
                }
            }
        }

        token::Client::new(&env, &intent.token).transfer(
            &env.current_contract_address(),
            &intent.sme,
            &intent.amount,
        );
        intent.status = Status::Refunded;
        env.storage().persistent().set(&Key::Intent(intent_id), &intent);
        Refunded {
            id: intent_id,
            sme: intent.sme.clone(),
            amount: intent.amount,
        }
        .publish(&env);
        Ok(())
    }

    pub fn get_intent(env: Env, intent_id: u64) -> Option<Intent> {
        env.storage().persistent().get(&Key::Intent(intent_id))
    }

    fn admin(env: &Env) -> Address {
        env.storage().instance().get(&Key::Admin).unwrap()
    }

    fn oracle_registered(env: &Env, oracle: &Address) -> bool {
        env.storage()
            .persistent()
            .get(&Key::Oracle(oracle.clone()))
            .unwrap_or(false)
    }

    fn load(env: &Env, intent_id: u64) -> Result<Intent, Error> {
        env.storage()
            .persistent()
            .get(&Key::Intent(intent_id))
            .ok_or(Error::IntentNotFound)
    }

    fn next_id(env: &Env) -> u64 {
        let next: u64 = env.storage().instance().get(&Key::Counter).unwrap_or(0) + 1;
        env.storage().instance().set(&Key::Counter, &next);
        next
    }
}

mod test;
