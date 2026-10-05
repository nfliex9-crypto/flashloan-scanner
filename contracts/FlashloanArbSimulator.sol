// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IERC20 {
    function approve(address spender, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
}

interface IAavePool {
    function flashLoanSimple(
        address receiverAddress,
        address asset,
        uint256 amount,
        bytes calldata params,
        uint16 referralCode
    ) external;

    function FLASHLOAN_PREMIUM_TOTAL() external view returns (uint128);
}

interface IUniswapV3Router {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 deadline;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }

    function exactInputSingle(
        ExactInputSingleParams calldata params
    ) external payable returns (uint256 amountOut);
}

interface ICamelotV3Router {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        address recipient;
        uint256 deadline;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 limitSqrtPrice;
    }

    function exactInputSingle(
        ExactInputSingleParams calldata params
    ) external payable returns (uint256 amountOut);
}

/// @notice Stage-3 execution contract for Arbitrum fork simulation.
/// @dev It is intentionally owner-only and has no automatic wallet integration.
///      The same contract can be tested against a fork without deploying to mainnet.
contract FlashloanArbSimulator {
    error NotOwner();
    error UnauthorizedCallback();
    error InvalidRoute();
    error ApproveFailed();
    error TransferFailed();
    error Unprofitable(uint256 finalBalance, uint256 requiredBalance);

    enum Dex {
        UniswapV3,
        CamelotV3
    }

    struct RouteParams {
        Dex buyDex;
        Dex sellDex;
        uint24 uniBuyFee;
        uint24 uniSellFee;
        uint256 minWethOut;
        uint256 minUsdcOut;
        uint256 minProfitUsdc;
    }

    address public constant AAVE_POOL = 0x794a61358D6845594F94dc1DB02A252b5b4814aD;
    address public constant USDC = 0xaf88d065e77c8cC2239327C5EDb3A432268e5831;
    address public constant WETH = 0x82aF49447D8a07e3bd95BD0d56f35241523fBab1;
    address public constant UNISWAP_V3_ROUTER = 0xE592427A0AEce92De3Edee1F18E0157C05861564;
    address public constant CAMELOT_V3_ROUTER = 0x1F721E2E82F6676FCE4eA07A5958cF098D339e18;

    address public immutable owner;

    event SimulationExecuted(
        Dex indexed buyDex,
        Dex indexed sellDex,
        uint256 borrowedUsdc,
        uint256 premiumUsdc,
        uint256 wethReceived,
        uint256 usdcReceived,
        uint256 profitUsdc
    );

    constructor() {
        owner = msg.sender;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    /// @notice Starts a real Aave flashLoanSimple call on the selected chain.
    /// @dev In Stage 3 this function is used only on an Arbitrum fork.
    function executeArbitrage(
        uint256 amountUsdc,
        RouteParams calldata route
    ) external onlyOwner returns (uint256 profitUsdc) {
        if (route.buyDex == route.sellDex) revert InvalidRoute();

        uint256 balanceBefore = IERC20(USDC).balanceOf(address(this));

        IAavePool(AAVE_POOL).flashLoanSimple(
            address(this),
            USDC,
            amountUsdc,
            abi.encode(route),
            0
        );

        uint256 balanceAfter = IERC20(USDC).balanceOf(address(this));
        profitUsdc = balanceAfter - balanceBefore;
    }

    /// @notice Aave V3 flash-loan callback.
    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external returns (bool) {
        if (
            msg.sender != AAVE_POOL ||
            initiator != address(this) ||
            asset != USDC
        ) revert UnauthorizedCallback();

        RouteParams memory route = abi.decode(params, (RouteParams));
        if (route.buyDex == route.sellDex) revert InvalidRoute();

        uint256 startingUsdc = IERC20(USDC).balanceOf(address(this));
        uint256 reserveUsdc = startingUsdc - amount;

        uint256 wethReceived = _swapUsdcToWeth(amount, route);
        uint256 usdcReceived = _swapWethToUsdc(wethReceived, route);

        uint256 finalUsdc = IERC20(USDC).balanceOf(address(this));
        uint256 requiredUsdc =
            reserveUsdc + amount + premium + route.minProfitUsdc;

        if (finalUsdc < requiredUsdc) {
            revert Unprofitable(finalUsdc, requiredUsdc);
        }

        _forceApprove(USDC, AAVE_POOL, amount + premium);

        emit SimulationExecuted(
            route.buyDex,
            route.sellDex,
            amount,
            premium,
            wethReceived,
            usdcReceived,
            finalUsdc - reserveUsdc - amount - premium
        );

        return true;
    }

    function _swapUsdcToWeth(
        uint256 amountIn,
        RouteParams memory route
    ) internal returns (uint256 amountOut) {
        if (route.buyDex == Dex.UniswapV3) {
            _forceApprove(USDC, UNISWAP_V3_ROUTER, amountIn);
            amountOut = IUniswapV3Router(UNISWAP_V3_ROUTER).exactInputSingle(
                IUniswapV3Router.ExactInputSingleParams({
                    tokenIn: USDC,
                    tokenOut: WETH,
                    fee: route.uniBuyFee,
                    recipient: address(this),
                    deadline: block.timestamp,
                    amountIn: amountIn,
                    amountOutMinimum: route.minWethOut,
                    sqrtPriceLimitX96: 0
                })
            );
        } else {
            _forceApprove(USDC, CAMELOT_V3_ROUTER, amountIn);
            amountOut = ICamelotV3Router(CAMELOT_V3_ROUTER).exactInputSingle(
                ICamelotV3Router.ExactInputSingleParams({
                    tokenIn: USDC,
                    tokenOut: WETH,
                    recipient: address(this),
                    deadline: block.timestamp,
                    amountIn: amountIn,
                    amountOutMinimum: route.minWethOut,
                    limitSqrtPrice: 0
                })
            );
        }
    }

    function _swapWethToUsdc(
        uint256 amountIn,
        RouteParams memory route
    ) internal returns (uint256 amountOut) {
        if (route.sellDex == Dex.UniswapV3) {
            _forceApprove(WETH, UNISWAP_V3_ROUTER, amountIn);
            amountOut = IUniswapV3Router(UNISWAP_V3_ROUTER).exactInputSingle(
                IUniswapV3Router.ExactInputSingleParams({
                    tokenIn: WETH,
                    tokenOut: USDC,
                    fee: route.uniSellFee,
                    recipient: address(this),
                    deadline: block.timestamp,
                    amountIn: amountIn,
                    amountOutMinimum: route.minUsdcOut,
                    sqrtPriceLimitX96: 0
                })
            );
        } else {
            _forceApprove(WETH, CAMELOT_V3_ROUTER, amountIn);
            amountOut = ICamelotV3Router(CAMELOT_V3_ROUTER).exactInputSingle(
                ICamelotV3Router.ExactInputSingleParams({
                    tokenIn: WETH,
                    tokenOut: USDC,
                    recipient: address(this),
                    deadline: block.timestamp,
                    amountIn: amountIn,
                    amountOutMinimum: route.minUsdcOut,
                    limitSqrtPrice: 0
                })
            );
        }
    }

    function _forceApprove(
        address token,
        address spender,
        uint256 amount
    ) internal {
        if (!IERC20(token).approve(spender, 0)) revert ApproveFailed();
        if (!IERC20(token).approve(spender, amount)) revert ApproveFailed();
    }

    function withdrawToken(
        address token,
        address to,
        uint256 amount
    ) external onlyOwner {
        if (!IERC20(token).transfer(to, amount)) revert TransferFailed();
    }
}
