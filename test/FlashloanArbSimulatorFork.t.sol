// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "../contracts/FlashloanArbSimulator.sol";

interface Vm {
    function createSelectFork(string calldata urlOrAlias) external returns (uint256);
    function envOr(string calldata name, string calldata defaultValue) external returns (string memory);
    function expectRevert() external;
    function expectRevert(bytes4 revertData) external;
}

contract FlashloanArbSimulatorForkTest {
    Vm internal constant vm =
        Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    FlashloanArbSimulator internal simulator;

    function setUp() public {
        string memory rpc = vm.envOr(
            "ARBITRUM_RPC_URL",
            string("https://arb1.arbitrum.io/rpc")
        );
        vm.createSelectFork(rpc);
        simulator = new FlashloanArbSimulator();
    }

    function testArbitrumContractsExist() public view {
        require(simulator.AAVE_POOL().code.length > 0, "Aave pool missing");
        require(simulator.UNISWAP_V3_ROUTER().code.length > 0, "Uniswap router missing");
        require(simulator.CAMELOT_V3_ROUTER().code.length > 0, "Camelot router missing");
        require(simulator.USDC().code.length > 0, "USDC missing");
        require(simulator.WETH().code.length > 0, "WETH missing");
    }

    function testAaveFlashLoanPremiumIsSane() public view {
        uint128 premium = IAavePool(simulator.AAVE_POOL()).FLASHLOAN_PREMIUM_TOTAL();
        require(premium > 0, "premium should be positive");
        require(premium < 100, "premium unexpectedly high");
    }

    function testUnauthorizedCallbackReverts() public {
        vm.expectRevert(FlashloanArbSimulator.UnauthorizedCallback.selector);
        simulator.executeOperation(
            simulator.USDC(),
            100e6,
            50_000,
            address(simulator),
            ""
        );
    }

    /// @dev This intentionally requires an impossible profit.
    ///      The flash loan + swaps execute against forked mainnet state,
    ///      then the contract must reject the trade at its safety guard.
    function testFlashLoanPathRevertsWhenProfitRequirementIsNotMet() public {
        FlashloanArbSimulator.RouteParams memory route =
            FlashloanArbSimulator.RouteParams({
                buyDex: FlashloanArbSimulator.Dex.CamelotV3,
                sellDex: FlashloanArbSimulator.Dex.UniswapV3,
                uniBuyFee: 100,
                uniSellFee: 100,
                minWethOut: 0,
                minUsdcOut: 0,
                minProfitUsdc: 1_000e6
            });

        vm.expectRevert();
        simulator.executeArbitrage(100e6, route);
    }
}
