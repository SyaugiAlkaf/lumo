#![no_std]
use soroban_sdk::{
    auth::{Context, CustomAccountInterface},
    contract, contracterror, contractimpl, contracttype,
    crypto::Hash,
    Address, Bytes, BytesN, Env, Symbol, TryIntoVal, Val, Vec,
};

#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
#[repr(u32)]
pub enum Error {
    FnNotAllowed = 1,
    OverCap = 2,
    SupplierNotApproved = 3,
    BadSignature = 4,
    InvalidArgs = 5,
    RecipientNotAllowed = 6,
}

#[contracttype]
#[derive(Clone)]
pub struct Ed25519Signature {
    pub public_key: BytesN<32>,
    pub signature: BytesN<64>,
}

#[contracttype]
#[derive(Clone)]
enum Key {
    Owner,
    Cap,
    Escrow,
    Supplier(Address),
}

const DAY_LEDGERS: u32 = 17280;
const BUMP_THRESHOLD: u32 = 30 * DAY_LEDGERS;
const BUMP_EXTEND: u32 = 90 * DAY_LEDGERS;

// Positional layout of escrow::create_intent(sme, supplier, token, amount,
// request_hash, deadline) — frozen at P1, guarded cross-crate against the real
// escrow ABI by guard_create_intent_arg_order in test.rs.
const CREATE_INTENT_SUPPLIER: u32 = 1;
const CREATE_INTENT_AMOUNT: u32 = 3;
// token::transfer(from, to, amount).
const TRANSFER_TO: u32 = 1;
const TRANSFER_AMOUNT: u32 = 2;

#[contract]
pub struct PolicyAccount;

#[contractimpl]
impl PolicyAccount {
    pub fn __constructor(env: Env, owner: BytesN<32>, cap_per_tx: i128) {
        env.storage().instance().set(&Key::Owner, &owner);
        env.storage().instance().set(&Key::Cap, &cap_per_tx);
    }

    pub fn add_supplier(env: Env, supplier: Address) {
        env.current_contract_address().require_auth();
        env.storage().persistent().set(&Key::Supplier(supplier.clone()), &());
        env.storage()
            .persistent()
            .extend_ttl(&Key::Supplier(supplier), BUMP_THRESHOLD, BUMP_EXTEND);
    }

    pub fn remove_supplier(env: Env, supplier: Address) {
        env.current_contract_address().require_auth();
        env.storage().persistent().remove(&Key::Supplier(supplier));
    }

    pub fn set_cap(env: Env, cap_per_tx: i128) {
        env.current_contract_address().require_auth();
        env.storage().instance().set(&Key::Cap, &cap_per_tx);
    }

    // The one escrow this account is allowed to fund. Until it is set, no token
    // transfer is authorized at all (fail-closed).
    pub fn set_escrow(env: Env, escrow: Address) {
        env.current_contract_address().require_auth();
        env.storage().instance().set(&Key::Escrow, &escrow);
    }

    pub fn escrow(env: Env) -> Option<Address> {
        env.storage().instance().get(&Key::Escrow)
    }

    pub fn owner(env: Env) -> BytesN<32> {
        env.storage().instance().get(&Key::Owner).unwrap()
    }

    pub fn cap(env: Env) -> i128 {
        env.storage().instance().get(&Key::Cap).unwrap()
    }

    pub fn is_supplier(env: Env, supplier: Address) -> bool {
        env.storage().persistent().has(&Key::Supplier(supplier))
    }
}

#[contractimpl(contracttrait)]
impl CustomAccountInterface for PolicyAccount {
    type Signature = Ed25519Signature;
    type Error = Error;

    #[allow(non_snake_case)]
    fn __check_auth(
        env: Env,
        signature_payload: Hash<32>,
        signature: Ed25519Signature,
        auth_contexts: Vec<Context>,
    ) -> Result<(), Error> {
        let owner: BytesN<32> = env.storage().instance().get(&Key::Owner).unwrap();
        if signature.public_key != owner {
            return Err(Error::BadSignature);
        }
        let payload: Bytes = signature_payload.into();
        env.crypto()
            .ed25519_verify(&signature.public_key, &payload, &signature.signature);

        let cap: i128 = env.storage().instance().get(&Key::Cap).unwrap();
        let curr = env.current_contract_address();
        for ctx in auth_contexts.iter() {
            check_context(&env, ctx, &curr, cap)?;
        }
        Ok(())
    }
}

fn check_context(env: &Env, ctx: Context, curr: &Address, cap: i128) -> Result<(), Error> {
    let c = match ctx {
        Context::Contract(c) => c,
        _ => return Err(Error::FnNotAllowed),
    };

    if &c.contract == curr {
        if c.fn_name == Symbol::new(env, "add_supplier")
            || c.fn_name == Symbol::new(env, "remove_supplier")
            || c.fn_name == Symbol::new(env, "set_cap")
            || c.fn_name == Symbol::new(env, "set_escrow")
        {
            return Ok(());
        }
        return Err(Error::FnNotAllowed);
    }

    if c.fn_name == Symbol::new(env, "create_intent") {
        let supplier: Address = arg(env, &c.args, CREATE_INTENT_SUPPLIER)?;
        if !env.storage().persistent().has(&Key::Supplier(supplier)) {
            return Err(Error::SupplierNotApproved);
        }
        return cap_ok(arg(env, &c.args, CREATE_INTENT_AMOUNT)?, cap);
    }

    if c.fn_name == Symbol::new(env, "transfer") {
        // The ONLY transfer this account authorizes is the sme -> escrow funding
        // leg of create_intent. Binding `to` to the configured escrow means a
        // compromised agent — even holding a valid owner signature — cannot move
        // funds to an attacker or a fake escrow. Fail closed if no escrow is set.
        let escrow: Address = env
            .storage()
            .instance()
            .get(&Key::Escrow)
            .ok_or(Error::RecipientNotAllowed)?;
        let to: Address = arg(env, &c.args, TRANSFER_TO)?;
        if to != escrow {
            return Err(Error::RecipientNotAllowed);
        }
        return cap_ok(arg(env, &c.args, TRANSFER_AMOUNT)?, cap);
    }

    Err(Error::FnNotAllowed)
}

fn arg<T>(env: &Env, args: &Vec<Val>, i: u32) -> Result<T, Error>
where
    Val: TryIntoVal<Env, T>,
{
    args.get(i)
        .ok_or(Error::InvalidArgs)?
        .try_into_val(env)
        .map_err(|_| Error::InvalidArgs)
}

fn cap_ok(amount: i128, cap: i128) -> Result<(), Error> {
    if amount < 0 {
        return Err(Error::InvalidArgs);
    }
    if amount > cap {
        return Err(Error::OverCap);
    }
    Ok(())
}

mod test;
